import os
import numpy as np
import logging
from typing import Any, Dict, Optional, Tuple

try:
    import onnxruntime as ort
except Exception:
    ort = None

try:
    from .base_engine import BaseInferenceEngine
except ImportError:
    # Fallback for different import contexts
    from base_engine import BaseInferenceEngine


class OnnxEngine(BaseInferenceEngine):
    """Inference engine for generic ONNX models.

    Expects the model to output a single tensor with shape:
        (1, 4 + num_classes, num_detections)

    The 4 are: x_center, y_center, width, height (in pixels or normalized depending on model).
    The remaining num_classes channels are the per-class confidence scores.
    """

    display_name = "ONNX Runtime"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_path = kwargs.get('model_path', self.model_path)
        self.device = kwargs.get('device', self.device)
        self.session: Optional[ort.InferenceSession] = None
        self.input_name: Optional[str] = None
        self.input_shape: Optional[Tuple[int, ...]] = None
        self.output_name: Optional[str] = None
        self.num_classes: Optional[int] = None
        # Confidence threshold for filtering predictions
        self.confidence_threshold: float = float(kwargs.get('confidence_threshold', 0.5))
        self.cat_map: Optional[Dict[int, str]] = kwargs.get('cat_map', None)
        # Track sizes to map model coordinates back to original image
        # types: Optional[Tuple[int,int]]
        self._original_image_size = None  # (height, width)
        self._model_input_size = None  # (width, height)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _load_model(self, model_file: str, device: str = "CPU") -> bool:
        if ort is None:
            self.logger.error("onnxruntime is not installed. Install with: pip install onnxruntime")
            return False

        if model_file is None or not os.path.exists(model_file):
            self.logger.error(f"ONNX model file not found: {model_file}")
            return False

        # Create provider list based on device
        providers = None
        device_lower = (device or "cpu").lower()
        if 'cuda' in device_lower:
            # Try CUDA provider first
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            provider_options = None
        elif 'gpu' in device_lower:
            providers = ['OpenVINOExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
            provider_options = [{'device_type': 'GPU'}, {'device_type': 'GPU'}, {'device_type': 'CPU'}]
        else:
            providers = ['OpenVINOExecutionProvider', 'CPUExecutionProvider']
            provider_options = [{'device_type': 'CPU'}, {'device_type': 'CPU'}]

        try:
            self.session = ort.InferenceSession(model_file, providers=providers, provider_options=provider_options)

            # Inspect inputs/outputs
            inputs = self.session.get_inputs()
            outputs = self.session.get_outputs()

            if len(inputs) == 0:
                raise RuntimeError("ONNX model has no inputs")

            # Use the first input
            inp = inputs[0]
            self.input_name = inp.name
            self.input_shape = tuple(dim if isinstance(dim, int) else -1 for dim in inp.shape)

            if len(outputs) == 0:
                raise RuntimeError("ONNX model has no outputs")

            # Expect single output with channels = 4 + num_classes
            out = outputs[0]
            self.output_name = out.name
            out_shape = out.shape  # may contain None or symbolic dims

            # Try to infer num_classes if possible
            # Expected shape: (1, 4+num_classes, num_detections)
            if len(out_shape) >= 3:
                # Replace non-int dims with -1
                normalized = [d if isinstance(d, int) else -1 for d in out_shape]
                if normalized[0] in (1, -1):
                    channels = normalized[1]
                    if isinstance(channels, int) and channels > 4:
                        self.num_classes = channels - 4

            self.model_path = model_file
            self.device = device
            self.is_loaded = True
            self.logger.info(f"Loaded ONNX model: {model_file} (input={self.input_shape}, output={out_shape})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load ONNX model: {e}")
            return False

    def check_valid_model(self, model_file: str) -> bool:
        if model_file is None:
            return False
        return model_file.lower().endswith('.onnx') and os.path.exists(model_file)

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess input image for ONNX model.

        Behavior / assumptions:
        - Input is a HxWxC BGR uint8 image (as OpenCV typically provides).
        - Converts to RGB, scales to [0,1], transposes to CHW and adds batch dim.
        - If the model input height/width are fixed and known, will resize to that.
        """
        if not isinstance(image, np.ndarray):
            raise TypeError("Input image must be a numpy array")

        img = image.copy()
        # Record original image size (height, width)
        if img.ndim >= 2:
            self._original_image_size = (int(img.shape[0]), int(img.shape[1]))
        else:
            self._original_image_size = None
        # Convert BGR -> RGB when we detect 3 channels
        if img.ndim == 3 and img.shape[2] == 3:
            img = img[:, :, ::-1]

        # If the model has a fixed spatial input, resize
        # Reset model input size each preprocess; we'll set it if we resize
        self._model_input_size = None
        if self.input_shape is not None and len(self.input_shape) >= 4:
            # input shape often like (batch, channels, height, width) or (batch, height, width, channels)
            shp = self.input_shape
            # try common patterns
            if shp[1] > 0 and shp[2] > 0 and shp[3] > 0:
                # assume NCHW
                expected_h = shp[2]
                expected_w = shp[3]
                # Store model input size as (width, height) for scaling later
                try:
                    import cv2
                    img = cv2.resize(img, (expected_w, expected_h))
                except Exception:
                    # If cv2 import/resize fails, fall back to numpy-based nearest neighbor resize
                    try:
                        from PIL import Image
                        img = np.array(Image.fromarray(img).resize((expected_w, expected_h)))
                    except Exception:
                        # As a last resort, leave the image unchanged
                        pass
                self._model_input_size = (int(expected_w), int(expected_h))
            elif shp[2] > 0 and shp[3] > 0 and shp[1] == -1:
                # fallback heuristics ignored
                pass

        # Normalize to 0..1
        img = img.astype(np.float32) / 255.0

        # Convert HWC -> CHW
        if img.ndim == 3:
            img = np.transpose(img, (2, 0, 1))
        else:
            # grayscale -> add channel dim
            img = np.expand_dims(img, 0)

        # Add batch dim
        img = np.expand_dims(img, 0)

        return img

    def _infer(self, preprocessed_input: np.ndarray) -> np.ndarray:
        if not self.is_loaded or self.session is None:
            raise RuntimeError("Model not loaded")

        # Prepare feed dict
        feed = {self.input_name: preprocessed_input.astype(np.float32)}
        outputs = self.session.run([self.output_name], feed)

        # Expect outputs[0] to be numpy array
        return outputs[0]

    def _postprocess(self, raw_output: np.ndarray) -> Dict[str, Any]:
        """Convert raw ONNX output to engine-standard dict.

        raw_output expected shape: (1, 4+classes, num_detections)
        We'll parse into list of detections where each detection includes bbox in x_center,y_center,w,h
        and a list of class confidences.
        """
        result: Dict[str, Any] = {
            "success": True,
            "device": self.device,
            "model_name": os.path.basename(self.model_path) if self.model_path else None,
            "predictions": [],
        }

        try:
            out = np.asarray(raw_output)

            # Ensure expected dims
            if out.ndim != 3:
                # Try to squeeze batch dim if present
                if out.ndim == 4 and out.shape[0] == 1:
                    out = out[0]
                else:
                    raise ValueError(f"Unexpected model output shape: {out.shape}")

            # If first dim is batch, remove it
            if out.shape[0] == 1:
                out = out[0]

            # Now out should be (channels, num_detections)
            if out.ndim != 2:
                raise ValueError(f"Unexpected post-squeezed output shape: {out.shape}")

            channels, num_dets = out.shape

            if channels < 5:
                raise ValueError(f"Output channels too small: {channels}. Expect at least 5 (4+1 class)")

            num_classes = channels - 4
            # For each detection, first 4 channels are bbox, remaining channels are class confidences
            for i in range(num_dets):
                bbox = out[0:4, i].tolist()  # [x_center, y_center, w, h]
                class_confidences = out[4:, i].tolist() if num_classes > 0 else []

                # Determine top class and score
                if class_confidences:
                    top_idx = int(np.argmax(class_confidences))
                    top_score = float(class_confidences[top_idx])
                else:
                    top_idx = -1
                    top_score = 0.0

                # Convert bbox from model/input coords to original image coords if possible
                # bbox is x_center, y_center, width, height in either absolute units (model input pixels)
                # or normalized [0,1]. We'll map to original image size when _original_image_size is known.
                x_c, y_c, bw, bh = bbox

                if self._original_image_size is not None:
                    orig_h, orig_w = self._original_image_size

                    if self._model_input_size is not None:
                        model_w, model_h = self._model_input_size
                        # If bbox values appear to be in model pixel space (greater than 1), scale by ratio
                        if any(v > 1.0 for v in [x_c, y_c, bw, bh]):
                            scale_x = orig_w / model_w if model_w > 0 else 1.0
                            scale_y = orig_h / model_h if model_h > 0 else 1.0
                            x_c = x_c * scale_x
                            bw = bw * scale_x
                            y_c = y_c * scale_y
                            bh = bh * scale_y
                        else:
                            # bbox appears normalized -> scale by original image size
                            x_c = x_c * orig_w
                            bw = bw * orig_w
                            y_c = y_c * orig_h
                            bh = bh * orig_h
                    else:
                        # No explicit model input size. Use normalization heuristic
                        if any(v > 1.0 for v in [x_c, y_c, bw, bh]):
                            # Assume already in original image coords
                            pass
                        else:
                            x_c = x_c * orig_w
                            bw = bw * orig_w
                            y_c = y_c * orig_h
                            bh = bh * orig_h

                # Update bbox to scaled values
                bbox = [x_c, y_c, bw, bh]

                # Filter by confidence threshold
                if top_score < self.confidence_threshold:
                    # Skip low-confidence detection
                    continue

                if self.cat_map:
                    # Map to external category name if provided
                    top_idx = self.cat_map.get(top_idx, "Other")

                det = {
                    "bbox": bbox,
                    "bbox_format": "xywh_center",
                    "class_confidences": class_confidences,
                    "top_class": top_idx,
                    "top_score": top_score,
                    "detection_index": i
                }
                result["predictions"].append(det)

            result["num_detections"] = len(result["predictions"])
            # Echo back the confidence threshold used
            result["confidence_threshold"] = float(self.confidence_threshold)
            return result

        except Exception as e:
            self.logger.error(f"ONNX postprocessing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "device": self.device
            }

    def draw(self, image: np.ndarray, results: Dict[str, Any]) -> np.ndarray:
        # Draw simple boxes using xywh center format
        import cv2
        out_img = image.copy()
        h, w = out_img.shape[:2]

        for pred in results.get('predictions', []):
            x_c, y_c, bw, bh = pred.get('bbox', [0, 0, 0, 0])

            # If bbox seems normalized (<=1), scale to image size
            if 0 < x_c <= 1 and 0 < y_c <= 1 and 0 < bw <= 1 and 0 < bh <= 1:
                x_c *= w
                y_c *= h
                bw *= w
                bh *= h

            x1 = int(x_c - bw / 2)
            y1 = int(y_c - bh / 2)
            x2 = int(x_c + bw / 2)
            y2 = int(y_c + bh / 2)

            cv2.rectangle(out_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{pred.get('top_class', -1)}:{pred.get('top_score', 0):.2f}"
            cv2.putText(out_img, label, (max(x1,0), max(y1-6,0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)

        return out_img

    def result_to_json(self, results: Dict[str, Any], output_format: str = "dict") -> Any:
        import json
        if output_format == 'dict':
            return results
        return json.dumps(results, indent=2)

"""
Slice Collector Node - collects predictions from multiple image slices and merges them.
Designed to work with SliceImageNode in a slice-detect-merge workflow.
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional
import numpy as np
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

_info = Info()
_info.add_text("Collects detection predictions from multiple image slices sent as separate messages, then merges them into a unified result.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Slice predictions from SliceImageNode. Auto-detects 'array' mode (all slices in one message) or 'split' mode (separate messages)."))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Merged predictions after all slices collected and NMS applied"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Timeout:", "Maximum time to wait for all slices before outputting partial results"),
    ("NMS IoU Threshold:", "Threshold for Non-Maximum Suppression"),
    ("Match Metric:", "IoU or IoS for duplicate detection matching"),
    ("Class Agnostic NMS:", "Apply NMS across all classes vs per-class"),
    ("Reconstruct Image from Slices:", "Rebuild the original parent image by stitching the collected tiles back together"),
    ("Draw Slice Bounds:", "Draw each slice's rectangle on the reconstructed image to visualize tile placement and overlap"),
)
_info.add_header("Usage")
_info.add_text("Works with either SliceImageNode output mode. Split: SliceImageNode (split) → Split → Inference → SliceCollectorNode. Array: SliceImageNode (array) → SliceCollectorNode")

@dataclass(frozen=True)
class NodeKeys:
    BBOX = 'bbox'
    SLICE_INDEX = 'slice_index'
    SLICE_OFFSET = 'slice_offset'
    SLICE_BBOX = 'slice_bbox'
    SLICES = 'slices'
    SLICE_COUNT = 'slice_count'
    COUNT = 'count'
    EXPECTED_COUNT = 'expected_count'
    OFFSET = 'offset'
    IS_FULL_IMAGE = 'is_full_image'
    ORIGINAL_WIDTH = 'original_width'
    ORIGINAL_HEIGHT = 'original_height'
    
    NMS_THRESHOLD = 'nms_threshold'
    MATCH_METRIC = 'match_metric'
    CLASS_AGNOSTIC = 'class_agnostic'
    TIMEOUT = 'timeout'
    RECONSTRUCT_IMAGE = 'reconstruct_image'
    DRAW_SLICE_BOUNDS = 'draw_slice_bounds'
    SLICE_IMAGE = 'slice_image'


class SliceCollectorNode(BaseNode):
    """
    Slice Collector Node - collects detection predictions from multiple image slices
    and merges them into a single unified result.
    
    This node is designed to pair with SliceImageNode in workflows like:
    
    SliceImageNode -> Split -> YOLONode -> SliceCollectorNode
    
    It tracks slice messages by their msg_id from the original slice operation,
    collects all predictions, transforms coordinates, and applies NMS.
    """
    display_name = 'Slice Collector'
    info = str(_info)
    icon = '📥'
    category = 'vision'
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        NodeKeys.TIMEOUT: 5.0,
        NodeKeys.NMS_THRESHOLD: 0.5,
        NodeKeys.MATCH_METRIC: 'iou',
        NodeKeys.CLASS_AGNOSTIC: False,
        NodeKeys.RECONSTRUCT_IMAGE: False,
        NodeKeys.DRAW_SLICE_BOUNDS: False,
        MessageKeys.DROP_MESSAGES: False
    }
    
    properties = [
        {
            'name': NodeKeys.TIMEOUT,
            'label': 'Collection Timeout (seconds)',
            'type': 'number',
            'default': DEFAULT_CONFIG[NodeKeys.TIMEOUT]
        },
        {
            'name': NodeKeys.NMS_THRESHOLD,
            'label': 'NMS IoU Threshold',
            'type': 'number',
            'default': DEFAULT_CONFIG[NodeKeys.NMS_THRESHOLD]
        },
        {
            'name': NodeKeys.MATCH_METRIC,
            'label': 'Match Metric',
            'type': 'select',
            'options': [
                {'value': 'iou', 'label': 'IoU (Intersection over Union)'},
                {'value': 'ios', 'label': 'IoS (Intersection over Smaller)'}
            ],
            'default': DEFAULT_CONFIG[NodeKeys.MATCH_METRIC]
        },
        {
            'name': NodeKeys.CLASS_AGNOSTIC,
            'label': 'Class Agnostic NMS',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG[NodeKeys.CLASS_AGNOSTIC]
        },
        {
            'name': NodeKeys.RECONSTRUCT_IMAGE,
            'label': 'Reconstruct Image from Slices',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG[NodeKeys.RECONSTRUCT_IMAGE]
        },
        {
            'name': NodeKeys.DRAW_SLICE_BOUNDS,
            'label': 'Draw Slice Bounds',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG[NodeKeys.DRAW_SLICE_BOUNDS],
            'showIf': {NodeKeys.RECONSTRUCT_IMAGE: True}
        }
    ]
    
    def __init__(self, node_id=None, name="slice_collector"):
        super().__init__(node_id, name)
        # Track collections by parent message ID
        self._collections: Dict[str, Dict] = {}
    
    def _calculate_iou(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoU between two bounding boxes in [x1, y1, x2, y2] format."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_ios(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoS (Intersection over Smaller) between two boxes."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        smaller = min(area1, area2)
        
        return intersection / smaller if smaller > 0 else 0.0
    
    def _transform_detections(self, detections: List[Dict], offset: List[int]) -> List[Dict]:
        """Transform detection coordinates from slice-local to original image coords."""
        transformed = []
        offset_x, offset_y = offset
        
        for det in detections:
            new_det = det.copy()
            bbox = det.get(NodeKeys.BBOX, [])
            
            if len(bbox) >= 4:
                x1, y1, x2, y2 = bbox[:4]
                new_det[NodeKeys.BBOX] = [x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y]
                new_det[NodeKeys.SLICE_OFFSET] = offset
            
            transformed.append(new_det)
        
        return transformed
    
    def _nms(self, detections: List[Dict], nms_threshold: float, 
             match_metric: str = NodeKeys.MATCH_METRIC, class_agnostic: bool = False) -> List[Dict]:
        """Apply Non-Maximum Suppression to remove duplicate detections."""
        if not detections:
            return []
        
        sorted_dets = sorted(detections, key=lambda x: x.get('confidence', 0), reverse=True)
        metric_fn = self._calculate_iou if match_metric == 'iou' else self._calculate_ios
        
        if class_agnostic:
            groups = {'all': sorted_dets}
        else:
            groups: Dict[Any, List[Dict]] = {}
            for det in sorted_dets:
                class_id = det.get('class_id', det.get('class_name', 'unknown'))
                if class_id not in groups:
                    groups[class_id] = []
                groups[class_id].append(det)
        
        kept = []
        for class_id, group in groups.items():
            keep_indices = []
            
            for i, det in enumerate(group):
                should_keep = True
                bbox_i = det.get(NodeKeys.BBOX, [])
                
                if len(bbox_i) < 4:
                    continue
                
                for j in keep_indices:
                    bbox_j = group[j].get(NodeKeys.BBOX, [])
                    if len(bbox_j) < 4:
                        continue
                    
                    if metric_fn(bbox_i, bbox_j) > nms_threshold:
                        should_keep = False
                        break
                
                if should_keep:
                    keep_indices.append(i)
            
            kept.extend([group[i] for i in keep_indices])
        
        return kept
    
    def _cleanup_expired(self):
        """Remove expired collections."""
        timeout = self.get_config_float(NodeKeys.TIMEOUT, self.DEFAULT_CONFIG[NodeKeys.TIMEOUT])
        current_time = time.time()
        expired = [k for k, v in self._collections.items() 
                   if current_time - v['start_time'] > timeout]
        for k in expired:
            del self._collections[k]
    
    def _process_collection(self, collection_id: str) -> Optional[Dict]:
        """Process a complete collection (by id) and return merged result."""
        collection = self._collections.get(collection_id)
        if not collection:
            return None
        return self._merge_collection(collection)
    
    def _merge_collection(self, collection: Dict) -> Optional[Dict]:
        """Merge all slices in a collection dict and return the merged result."""
        nms_threshold = self.get_config_float(NodeKeys.NMS_THRESHOLD, self.DEFAULT_CONFIG[NodeKeys.NMS_THRESHOLD])
        match_metric = self.config.get(NodeKeys.MATCH_METRIC, self.DEFAULT_CONFIG[NodeKeys.MATCH_METRIC])
        class_agnostic = self.get_config_bool(NodeKeys.CLASS_AGNOSTIC, self.DEFAULT_CONFIG[NodeKeys.CLASS_AGNOSTIC])
        
        all_detections = []
        full_image_detections = []
        
        for slice_data in collection[NodeKeys.SLICES].values():
            offset = slice_data.get(NodeKeys.OFFSET, [0, 0])
            detections = slice_data.get(MessageKeys.CV.DETECTIONS, [])
            is_full_image = slice_data.get(NodeKeys.IS_FULL_IMAGE, False)
            
            if is_full_image:
                full_image_detections.extend(detections)
            else:
                transformed = self._transform_detections(detections, offset)
                all_detections.extend(transformed)
        
        # Apply NMS
        merged = self._nms(all_detections, nms_threshold, match_metric, class_agnostic)
        
        # Combine with full image detections if present
        if full_image_detections:
            combined = merged + full_image_detections
            final_detections = self._nms(combined, nms_threshold, match_metric, class_agnostic)
        else:
            final_detections = merged
        
        # Sort by confidence
        final_detections = sorted(final_detections, key=lambda x: x.get(MessageKeys.CV.CONFIDENCE, 0), reverse=True)
        
        result = {
            MessageKeys.CV.DETECTIONS: final_detections,
            MessageKeys.CV.DETECTION_COUNT: len(final_detections),
            NodeKeys.ORIGINAL_WIDTH: collection.get(NodeKeys.ORIGINAL_WIDTH, 0),
            NodeKeys.ORIGINAL_HEIGHT: collection.get(NodeKeys.ORIGINAL_HEIGHT, 0),
            NodeKeys.SLICE_COUNT: len(collection[NodeKeys.SLICES]),
            MessageKeys.CV.BBOX_FORMAT: 'xyxy',
            MessageKeys.IMAGE.PATH: collection.get(MessageKeys.IMAGE.PATH)
        }
        
        # Optionally rebuild the parent image from the collected tiles
        if self.get_config_bool(NodeKeys.RECONSTRUCT_IMAGE, self.DEFAULT_CONFIG[NodeKeys.RECONSTRUCT_IMAGE]):
            reconstructed = self._reconstruct_image(collection)
            if reconstructed is not None:
                result[MessageKeys.IMAGE.PATH] = reconstructed
        
        return result
    
    def _reconstruct_image(self, collection: Dict) -> Optional[Any]:
        """
        Rebuild the original parent image by stitching the collected slice
        tiles back into a single canvas sized to the original image.
        
        Tiles are placed using their slice bbox (or offset). Overlapping
        regions are overwritten; if a full-image slice is present it is used
        as the base before overlaying the tiles.
        """
        if not _HAS_CV2:
            self.report_error("OpenCV (cv2) is required to reconstruct the image from slices")
            return None
        
        width = collection.get(NodeKeys.ORIGINAL_WIDTH, 0)
        height = collection.get(NodeKeys.ORIGINAL_HEIGHT, 0)
        
        if width <= 0 or height <= 0:
            self.report_error("Cannot reconstruct image: unknown original dimensions")
            return None
        
        canvas = None
        encode_format = None
        tile_bounds: List[tuple] = []
        
        # Place the full image (if any) first, then overlay tiles on top
        ordered_slices = sorted(
            collection[NodeKeys.SLICES].values(),
            key=lambda s: 0 if s.get(NodeKeys.IS_FULL_IMAGE, False) else 1
        )
        
        for slice_data in ordered_slices:
            img_payload = slice_data.get(NodeKeys.SLICE_IMAGE)
            if img_payload is None:
                continue
            
            slice_img, fmt = self.decode_image(img_payload)
            if slice_img is None:
                continue
            
            if encode_format is None:
                encode_format = fmt
            
            if canvas is None:
                if slice_img.ndim == 3:
                    canvas = np.zeros((height, width, slice_img.shape[2]), dtype=slice_img.dtype)
                else:
                    canvas = np.zeros((height, width), dtype=slice_img.dtype)
            
            sh, sw = slice_img.shape[:2]
            is_full_image = slice_data.get(NodeKeys.IS_FULL_IMAGE, False)
            
            if is_full_image:
                x1, y1 = 0, 0
            else:
                bbox = slice_data.get(NodeKeys.SLICE_BBOX)
                if bbox and len(bbox) >= 4:
                    x1, y1 = int(bbox[0]), int(bbox[1])
                else:
                    offset = slice_data.get(NodeKeys.OFFSET, [0, 0])
                    x1, y1 = int(offset[0]), int(offset[1])
            
            x1 = max(0, min(x1, width))
            y1 = max(0, min(y1, height))
            x2 = min(x1 + sw, width)
            y2 = min(y1 + sh, height)
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            canvas[y1:y2, x1:x2] = slice_img[0:(y2 - y1), 0:(x2 - x1)]
            
            # Record tile bounds for optional overlay (exclude the full image)
            if not is_full_image:
                tile_bounds.append((x1, y1, x2, y2))
        
        if canvas is None:
            return None
        
        # Optionally draw the slice bounds so the overlap is visible
        if self.get_config_bool(NodeKeys.DRAW_SLICE_BOUNDS, self.DEFAULT_CONFIG[NodeKeys.DRAW_SLICE_BOUNDS]):
            self._draw_slice_bounds(canvas, tile_bounds)
        
        return self.encode_image(canvas, encode_format)
    
    def _draw_slice_bounds(self, canvas: Any, tile_bounds: List[tuple]):
        """
        Draw a rectangle for each slice on the reconstructed canvas so the user
        can see where each tile sits and how much adjacent tiles overlap.
        """
        if not _HAS_CV2 or not tile_bounds:
            return
        
        # Cycle through distinct colors (BGR) so adjacent tiles are easy to tell apart
        colors = [
            (0, 255, 0),    # green
            (0, 0, 255),    # red
            (255, 0, 0),    # blue
            (0, 255, 255),  # yellow
            (255, 0, 255),  # magenta
            (255, 255, 0),  # cyan
        ]
        
        # Scale line thickness with image size for visibility on large images
        max_dim = max(canvas.shape[0], canvas.shape[1])
        thickness = max(1, max_dim // 500)
        
        for i, (x1, y1, x2, y2) in enumerate(tile_bounds):
            color = colors[i % len(colors)]
            # Inset by half the thickness so edge tiles' borders stay visible
            cv2.rectangle(  # type: ignore[union-attr]
                canvas,
                (int(x1), int(y1)),
                (int(x2) - 1, int(y2) - 1),
                color,
                thickness
            )
    
    def _handle_array(self, msg: Dict[str, Any], slices: List[Any]):
        """
        Handle 'array' output mode from SliceImageNode where every slice arrives
        together in a single message as a list. All slices are available at once,
        so the collection is built and merged immediately (no buffering/timeout).
        """
        collection: Dict[str, Any] = {
            NodeKeys.SLICES: {},
            NodeKeys.ORIGINAL_WIDTH: msg.get(NodeKeys.ORIGINAL_WIDTH, 0),
            NodeKeys.ORIGINAL_HEIGHT: msg.get(NodeKeys.ORIGINAL_HEIGHT, 0),
            MessageKeys.IMAGE.PATH: None
        }
        
        for i, item in enumerate(slices):
            if not isinstance(item, dict):
                continue
            
            item_payload = item.get(MessageKeys.PAYLOAD, {})
            if not isinstance(item_payload, dict):
                item_payload = {}
            
            offset = item.get(NodeKeys.OFFSET, item_payload.get(NodeKeys.OFFSET, [0, 0]))
            slice_bbox = item.get(NodeKeys.BBOX,
                                  item.get(NodeKeys.SLICE_BBOX, item_payload.get(NodeKeys.BBOX)))
            is_full_image = item.get(NodeKeys.IS_FULL_IMAGE, item_payload.get(NodeKeys.IS_FULL_IMAGE, False))
            slice_index = item.get(NodeKeys.SLICE_INDEX, i)
            detections = item_payload.get(MessageKeys.CV.DETECTIONS,
                                          item.get(MessageKeys.CV.DETECTIONS, []))
            image = item_payload.get(MessageKeys.IMAGE.PATH, item.get(MessageKeys.IMAGE.PATH))
            
            ow = item.get(NodeKeys.ORIGINAL_WIDTH, item_payload.get(NodeKeys.ORIGINAL_WIDTH, 0))
            oh = item.get(NodeKeys.ORIGINAL_HEIGHT, item_payload.get(NodeKeys.ORIGINAL_HEIGHT, 0))
            if ow > 0:
                collection[NodeKeys.ORIGINAL_WIDTH] = ow
            if oh > 0:
                collection[NodeKeys.ORIGINAL_HEIGHT] = oh
            
            collection[NodeKeys.SLICES][slice_index] = {
                MessageKeys.CV.DETECTIONS: detections,
                NodeKeys.OFFSET: offset,
                NodeKeys.SLICE_BBOX: slice_bbox,
                NodeKeys.SLICE_IMAGE: image,
                NodeKeys.IS_FULL_IMAGE: is_full_image
            }
            
            if is_full_image and image is not None:
                collection[MessageKeys.IMAGE.PATH] = image
        
        if not collection[NodeKeys.SLICES]:
            self.report_error("No slices found in array-mode message")
            return
        
        result = self._merge_collection(collection)
        if result:
            out_msg = msg.copy()
            out_msg[MessageKeys.PAYLOAD] = result
            out_msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'merged_predictions')
            out_msg.pop('parts', None)
            self.send(out_msg)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Collect slice predictions and merge when complete.
        
        Works seamlessly with either SliceImageNode output mode:
        
        - 'array' mode: all slices arrive together in one message where
          'payload' is a list of slice dicts. Merged immediately.
        - 'split' mode: each slice arrives as its own message (buffered by
          parent id via 'parts', merged once all slices are collected).
        
        Expected 'split' msg format (from Split of SliceImageNode, processed by YOLO):
        {
            'payload': {
                'image': ...,
                'detections': [...],
                ...
            },
            'parts': {
                'index': int,
                'count': int,
                'id': str  # Parent message ID
            },
            'slice_offset': [x, y],  # From SliceImageNode
            'slice_index': int,
            'is_full_image': bool,
            'original_width': int,
            'original_height': int
        }
        """
        self._cleanup_expired()
        
        payload = msg.get(MessageKeys.PAYLOAD, {})
        
        # Auto-detect output mode from SliceImageNode:
        #   - 'array' mode: payload is a list of all slices in one message
        #   - 'split' mode: payload is a single slice dict across many messages
        if isinstance(payload, list):
            self._handle_array(msg, payload)
            return
        
        parts = msg.get('parts', {})
        
        # Get collection ID (from parts or generate one)
        collection_id = parts.get('id', msg.get(MessageKeys.MSG_ID, 'default'))
        expected_count = parts.get('count', 1)
        slice_index = parts.get('index', msg.get(NodeKeys.SLICE_INDEX, 0))
        
        # Get slice metadata (check message level first, then payload).
        # SliceImageNode emits these at message level as 'slice_offset' / 'slice_bbox'.
        offset = msg.get(NodeKeys.SLICE_OFFSET,
                         msg.get(NodeKeys.OFFSET,
                                 payload.get(NodeKeys.OFFSET, [0, 0]) if isinstance(payload, dict) else [0, 0]))
        slice_bbox = msg.get(NodeKeys.SLICE_BBOX,
                             msg.get(NodeKeys.BBOX,
                                     payload.get(NodeKeys.BBOX, None) if isinstance(payload, dict) else None))
        is_full_image = msg.get(NodeKeys.IS_FULL_IMAGE, payload.get(NodeKeys.IS_FULL_IMAGE, False) if isinstance(payload, dict) else False)
        original_width = msg.get(NodeKeys.ORIGINAL_WIDTH, payload.get(NodeKeys.ORIGINAL_WIDTH, 0) if isinstance(payload, dict) else 0)
        original_height = msg.get(NodeKeys.ORIGINAL_HEIGHT, payload.get(NodeKeys.ORIGINAL_HEIGHT, 0) if isinstance(payload, dict) else 0)
        
        # Get detections
        if isinstance(payload, dict):
            detections = payload.get(MessageKeys.CV.DETECTIONS, [])
            image = payload.get(MessageKeys.IMAGE.PATH)
        else:
            detections = []
            image = None
        
        # Initialize collection if needed
        if collection_id not in self._collections:
            self._collections[collection_id] = {
                'start_time': time.time(),
                NodeKeys.EXPECTED_COUNT: expected_count,
                NodeKeys.SLICES: {},
                NodeKeys.ORIGINAL_WIDTH: original_width,
                NodeKeys.ORIGINAL_HEIGHT: original_height,
                MessageKeys.ORIGINAL_MSG: msg.copy(),
                MessageKeys.IMAGE.PATH: None
            }
        
        collection = self._collections[collection_id]
        
        # Store slice data
        collection[NodeKeys.SLICES][slice_index] = {
            MessageKeys.CV.DETECTIONS: detections,
            NodeKeys.OFFSET: offset,
            NodeKeys.SLICE_BBOX: slice_bbox,
            NodeKeys.SLICE_IMAGE: image,
            NodeKeys.IS_FULL_IMAGE: is_full_image
        }
        
        # Store full image if this is the full image slice
        if is_full_image and image is not None:
            collection[MessageKeys.IMAGE.PATH] = image
        
        # Update dimensions if available
        if original_width > 0:
            collection[NodeKeys.ORIGINAL_WIDTH] = original_width
        if original_height > 0:
            collection[NodeKeys.ORIGINAL_HEIGHT] = original_height
        
        # Check if complete
        if len(collection[NodeKeys.SLICES]) >= collection[NodeKeys.EXPECTED_COUNT]:
            result = self._process_collection(collection_id)
            
            if result:
                out_msg = collection[MessageKeys.ORIGINAL_MSG].copy()
                out_msg[MessageKeys.PAYLOAD] = result
                out_msg[MessageKeys.TOPIC] = out_msg.get(MessageKeys.TOPIC, 'merged_predictions')
                
                # Clean up parts since we've merged
                out_msg.pop('parts', None)
                
                self.send(out_msg)
            
            # Clean up
            del self._collections[collection_id]

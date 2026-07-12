"""
Omron Camera node - captures frames from OMRON Sentech GigE cameras using STAPI.

Compatible with the existing gigecams library (optional dependency for Bayer conversion).
Supports connection by device index or IP address, and multiple working modes.

Message output format matches CameraNode / FrameSourceNode for drop-in compatibility.
"""

import base64
import logging
import threading
import time
import queue
import ipaddress
from typing import Any, Dict, Optional

import numpy as np

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# STAPI lazy import
# ---------------------------------------------------------------------------
_st: Any = None  # module will be set on first successful import


def _get_stapi():
    """Lazy-import stapipy. Returns the module or None."""
    global _st
    if _st is not None:
        return _st
    try:
        import stapipy as m
        _st = m
        return _st
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Optional gigecams converter
# ---------------------------------------------------------------------------
_has_gigecams = False
_gige_bayer_to_rgb = None


def _try_load_gigecams():
    """Try to import Bayer converter from gigecams (non-fatal if missing)."""
    global _has_gigecams, _gige_bayer_to_rgb
    if _has_gigecams:
        return True
    try:
        from gigecams.convert import bayer_to_rgb
        _gige_bayer_to_rgb = bayer_to_rgb
        _has_gigecams = True
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Info panel
# ---------------------------------------------------------------------------
_info = Info()
_info.add_text(
    "Captures frames from OMRON Sentech GigE cameras using the STAPI SDK "
    "(Sentech Transfer API). Supports connection by device index or IP address."
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Frame message with image data (numpy array or JPEG encoded)."),
)
_info.add_header("Connection")
_info.add_bullets(
    ("Camera Index:", "Connects by enumerating detected devices (0 = first camera)."),
    ("IP Address:", "Connects to a specific camera by its GigE IP."),
)
_info.add_header("Working Modes")
_info.add_bullets(
    ("Continuous:", "Free-running acquisition at the configured FPS."),
    ("SoftwareTrigger:", "Camera waits for a software trigger signal to capture one frame."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Exposure Time:", "Microseconds."),
    ("FPS:", "Target output frame rate (and camera frame rate in Continuous mode)."),
    ("Width / Height:", "Resolution. Falls back to camera defaults if not supported."),
    ("Encode as JPEG:", "Base64 JPEG output instead of raw numpy array."),
)


# ===================================================================
# Node
# ===================================================================
class OmronCameraNode(BaseNode):
    """
    Omron Camera node - captures frames from OMRON Sentech GigE cameras.

    Uses the STAPI SDK (stapipy) for camera communication. Can optionally
    import from the ``gigecams`` library for Bayer-to-RGB conversion.
    """

    display_name = "Omron Camera"
    icon = "📷"
    category = "input"
    color = "#C0DEED"
    border_color = "#7FA7C9"
    text_color = "#000000"
    input_count = 0
    output_count = 1
    info = str(_info)

    # ------------------------------------------------------------------
    # Configuration schema
    # ------------------------------------------------------------------
    DEFAULT_CONFIG = {
        "connection_type": "index",           # "index" | "ip"
        "camera_index": 0,
        "camera_ip": "",
        "working_mode": "Continuous",         # "Continuous" | "SoftwareTrigger"
        "exposure_time": 5000,                # microseconds
        "fps": 30,
        "width": 640,
        "height": 480,
        "encode_jpeg": False,
        "jpeg_quality": 75,
    }

    properties = [
        {
            "name": "connection_type",
            "label": "Connection Type",
            "type": "select",
            "options": [
                {"value": "index", "label": "Camera Index"},
                {"value": "ip", "label": "IP Address"},
            ],
            "default": DEFAULT_CONFIG["connection_type"],
        },
        {
            "name": "camera_index",
            "label": "Camera Index",
            "type": "number",
            "default": DEFAULT_CONFIG["camera_index"],
            "showIf": {"connection_type": "index"},
        },
        {
            "name": "camera_ip",
            "label": "Camera IP Address",
            "type": "text",
            "default": DEFAULT_CONFIG["camera_ip"],
            "showIf": {"connection_type": "ip"},
            "placeholder": "e.g. 192.168.0.100",
        },
        {
            "name": "working_mode",
            "label": "Working Mode",
            "type": "select",
            "options": [
                {"value": "Continuous", "label": "Continuous (Free-run)"},
                {"value": "SoftwareTrigger", "label": "Software Trigger"},
            ],
            "default": DEFAULT_CONFIG["working_mode"],
        },
        {
            "name": "exposure_time",
            "label": "Exposure Time (µs)",
            "type": "number",
            "default": DEFAULT_CONFIG["exposure_time"],
        },
        {
            "name": "fps",
            "label": "Output Frame Rate (FPS)",
            "type": "number",
            "default": DEFAULT_CONFIG["fps"],
        },
        {
            "name": "width",
            "label": "Width",
            "type": "number",
            "default": DEFAULT_CONFIG["width"],
        },
        {
            "name": "height",
            "label": "Height",
            "type": "number",
            "default": DEFAULT_CONFIG["height"],
        },
        {
            "name": "encode_jpeg",
            "label": "Encode as JPEG",
            "type": "checkbox",
            "default": DEFAULT_CONFIG["encode_jpeg"],
        },
        {
            "name": "jpeg_quality",
            "label": "JPEG Quality (1-100)",
            "type": "number",
            "default": DEFAULT_CONFIG["jpeg_quality"],
            "showIf": {"encode_jpeg": True},
        },
    ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __init__(self, node_id: Optional[str] = None, name: str = "omron_camera"):
        super().__init__(node_id, name)

        # STAPI handles
        self._st_system: Any = None
        self._st_device: Any = None
        self._st_datastream: Any = None
        self._callback_handle: Any = None
        self._trigger_software_cmd: Any = None
        self._st_initialized: bool = False

        # Frame transport
        self._frame_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=8)
        self._cv2: Any = None

        # Threading
        self.capture_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self._frame_count: int = 0

    # -- start ---------------------------------------------------------
    def on_start(self):
        """Connect to the Omron camera, configure it, and begin acquisition."""
        super().on_start()

        # --- validate dependencies ---
        st = _get_stapi()
        if st is None:
            self.report_error(
                "stapipy is not installed. Install the OMRON Sentech STAPI SDK "
                "(pip install stapipy or use the .whl from gigecams/Omron/)."
            )
            return

        import cv2 as _cv2
        self._cv2 = _cv2
        _try_load_gigecams()

        connection_type = self.config.get("connection_type", "index")
        working_mode = self.config.get("working_mode", "Continuous")
        exposure_time = self.get_config_int("exposure_time", 5000)
        fps = self.get_config_int("fps", 30)

        try:
            # 1. Initialise STAPI
            st.initialize()
            self._st_initialized = True

            # 2. Connect to device
            if connection_type == "ip":
                camera_ip = self.config.get("camera_ip", "").strip()
                if not camera_ip:
                    self.report_error("IP address is empty.")
                    return
                self._connect_by_ip(st, camera_ip)
            else:
                idx = self.get_config_int("camera_index", 0)
                self._connect_by_index(st, idx)

            dev_name = self._st_device.info.display_name
            logger.info(f"[OmronCamera] Connected to {dev_name}")

            # 3. Configure GenICam nodes
            nodemap = self._st_device.remote_port.nodemap
            self._configure_nodemap(st, nodemap, working_mode, exposure_time, fps)

            # 4. Create data stream & register callback
            self._st_datastream = self._st_device.create_datastream()
            self._callback_handle = self._st_datastream.register_callback(
                self._on_stapi_buffer,
                None,  # context (unused — we use self)
            )

            # 5. Keep a handle to TriggerSoftware for later software-trigger calls
            if working_mode == "SoftwareTrigger":
                try:
                    node = nodemap.get_node("TriggerSoftware")
                    self._trigger_software_cmd = st.PyICommand(node)
                except Exception as exc:
                    logger.warning(f"[OmronCamera] Could not get TriggerSoftware node: {exc}")

            # 6. Start acquisition
            self._st_datastream.start_acquisition()
            self._st_device.acquisition_start()
            logger.info(f"[OmronCamera] Acquisition started ({working_mode})")

            # 7. Launch capture thread
            self.running = True
            self._frame_count = 0
            self.capture_thread = threading.Thread(
                target=self._capture_loop,
                args=(fps,),
                daemon=True,
            )
            self.capture_thread.start()

        except Exception as exc:
            self.report_error(f"Failed to start Omron camera: {exc}")
            self._teardown_stapi()

    # -- stop ----------------------------------------------------------
    def on_stop(self):
        """Stop acquisition and release all STAPI resources."""
        super().on_stop()
        self.running = False

        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
            self.capture_thread = None

        self._teardown_stapi()

    def on_close(self):
        """Cleanup on node deletion."""
        self.on_stop()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect_by_index(self, st, index: int):
        """Connect to the *index*-th camera found on the first interface."""
        self._st_system = st.create_system()
        dev = None
        # create_first_device() always returns the first.  To get the Nth
        # device we iterate and collect, then pick the Nth.
        candidates: list = []
        while True:
            try:
                candidates.append(self._st_system.create_first_device())
            except Exception:
                break
        if index >= len(candidates):
            raise RuntimeError(
                f"Only {len(candidates)} camera(s) found, cannot use index {index}."
            )
        self._st_device = candidates[index]

    def _connect_by_ip(self, st, ip_str: str):
        """Scan all interfaces and connect to the device with matching IP."""
        ip_int = int(ipaddress.ip_address(ip_str))
        self._st_system = st.create_system()

        for if_idx in range(self._st_system.interface_count):
            iface = self._st_system.get_interface(if_idx)
            iface.update_device_list()
            iface_nodemap = iface.port.nodemap

            dev_selector = iface_nodemap.get_node("DeviceSelector")
            ip_node = iface_nodemap.get_node("GevDeviceIPAddress")

            # Determine max device index
            try:
                max_idx = int(dev_selector.max)
            except Exception:
                max_idx = 64  # safe upper bound

            for dev_idx in range(max_idx + 1):
                try:
                    dev_selector.value = dev_idx
                    if ip_node.is_available and ip_node.value == ip_int:
                        self._st_device = iface.create_device_by_index(dev_idx)
                        return
                except Exception:
                    continue

        raise RuntimeError(f"Camera with IP {ip_str} not found on any interface.")

    # ------------------------------------------------------------------
    # GenICam configuration
    # ------------------------------------------------------------------
    def _configure_nodemap(self, st, nodemap, mode: str, exp_us: int, fps: int):
        """Apply user configuration to the camera's remote nodemap."""

        # --- ExposureTime ---
        try:
            node = nodemap.get_node("ExposureTime")
            itype = node.principal_interface_type
            if itype == st.EGCInterfaceType.IFloat:
                obj = st.PyIFloat(node)
                obj.value = float(exp_us)
            elif itype == st.EGCInterfaceType.IInteger:
                obj = st.PyIInteger(node)
                obj.value = int(exp_us)
        except Exception as exc:
            logger.warning(f"[OmronCamera] Could not set ExposureTime: {exc}")

        # --- AcquisitionFrameRate ---
        try:
            fr_node = nodemap.get_node("AcquisitionFrameRate")
            fr = st.PyIFloat(fr_node)
            fr.value = float(fps)
        except Exception:
            pass  # not all cameras support this

        # --- Resolution (Width / Height) ---
        w_val = self.get_config_int("width", 640)
        h_val = self.get_config_int("height", 480)
        try:
            w = st.PyIInteger(nodemap.get_node("Width"))
            w.value = w_val
        except Exception:
            logger.warning(f"[OmronCamera] Width {w_val} not supported, using default.")
        try:
            h = st.PyIInteger(nodemap.get_node("Height"))
            h.value = h_val
        except Exception:
            logger.warning(f"[OmronCamera] Height {h_val} not supported, using default.")

        # --- Trigger configuration ---
        if mode == "SoftwareTrigger":
            # TriggerSelector → FrameStart (fallback ExposureStart)
            try:
                ts = st.PyIEnumeration(nodemap.get_node("TriggerSelector"))
                ts.set_symbolic_value("FrameStart")
            except Exception:
                try:
                    ts.set_symbolic_value("ExposureStart")
                except Exception as exc:
                    logger.warning(f"[OmronCamera] Could not set TriggerSelector: {exc}")

            # TriggerMode → On
            try:
                tm = st.PyIEnumeration(nodemap.get_node("TriggerMode"))
                tm.set_symbolic_value("On")
            except Exception as exc:
                logger.warning(f"[OmronCamera] Could not set TriggerMode: {exc}")

            # TriggerSource → Software
            try:
                src = st.PyIEnumeration(nodemap.get_node("TriggerSource"))
                src.set_symbolic_value("Software")
            except Exception as exc:
                logger.warning(f"[OmronCamera] Could not set TriggerSource: {exc}")
        else:
            # Continuous → TriggerMode Off
            try:
                tm = st.PyIEnumeration(nodemap.get_node("TriggerMode"))
                tm.set_symbolic_value("Off")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # STAPI buffer callback  (invoked from STAPI internal thread)
    # ------------------------------------------------------------------
    def _on_stapi_buffer(self, handle, context):
        """Called by STAPI when a new buffer arrives. Pushes frame into a queue."""
        if not self.running:
            return
        st = _get_stapi()
        if st is None:
            return

        try:
            if handle.callback_type != st.EStCallbackType.GenTLDataStreamNewBuffer:
                return
        except Exception:
            return

        try:
            with self._st_datastream.retrieve_buffer(100) as st_buffer:
                if not st_buffer.info.is_image_present:
                    return

                st_image = st_buffer.get_image()
                frame = self._stapi_image_to_numpy(st, st_image)
                if frame is None:
                    return

                # Non-blocking push; drop oldest if full (keep latest frame)
                try:
                    self._frame_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._frame_queue.get_nowait()
                        self._frame_queue.put_nowait(frame)
                    except queue.Empty:
                        pass

        except Exception as exc:
            # Silently swallow transient STAPI errors in callback
            if self.running:
                logger.error(f"[OmronCamera] Callback error: {exc}")

    # ------------------------------------------------------------------
    # Image conversion
    # ------------------------------------------------------------------
    def _stapi_image_to_numpy(self, st, st_image) -> Optional[np.ndarray]:
        """Convert a STAPI image to a BGR numpy array."""
        raw = st_image.get_image_data()
        arr = np.frombuffer(raw, dtype=np.uint8)
        h, w = st_image.height, st_image.width

        # Try gigecams converter first
        if _has_gigecams and _gige_bayer_to_rgb is not None:
            try:
                bayer_frame, _ = _gige_bayer_to_rgb(st_image)
                return bayer_frame
            except Exception:
                pass  # fall through

        # Pixel-format-aware conversion
        try:
            pix_fmt = st_image.pixel_format
        except Exception:
            pix_fmt = None

        cv2 = self._cv2

        if pix_fmt == st.EStPixelFormatNamingConvention.BayerRG8:
            # Bayer RG8 → BGR via OpenCV
            bayer = arr.reshape(h, w)
            return cv2.cvtColor(bayer, cv2.COLOR_BayerRG2BGR)

        elif pix_fmt == st.EStPixelFormatNamingConvention.BGR8:
            return arr.reshape(h, w, 3)

        elif pix_fmt == st.EStPixelFormatNamingConvention.Mono8:
            gray = arr.reshape(h, w)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        elif pix_fmt == st.EStPixelFormatNamingConvention.RGB8:
            rgb = arr.reshape(h, w, 3)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        else:
            # Blind fallback: try 3-channel first, then 1-channel → gray2bgr
            try:
                return arr.reshape(h, w, 3)
            except Exception:
                try:
                    gray = arr.reshape(h, w)
                    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                except Exception as exc:
                    logger.error(f"[OmronCamera] Cannot convert image: {exc}")
                    return None

    # ------------------------------------------------------------------
    # Capture loop
    # ------------------------------------------------------------------
    def _capture_loop(self, target_fps: int):
        """Poll the frame queue at the configured rate and emit messages."""
        interval = 1.0 / max(target_fps, 1)
        encode_jpeg = self.config.get("encode_jpeg", False)

        while self.running:
            t_start = time.time()

            try:
                frame = self._frame_queue.get(timeout=interval)
            except queue.Empty:
                continue

            if frame is None:
                continue

            # --- encode payload ---
            if encode_jpeg:
                quality = self.get_config_int("jpeg_quality", 75)
                ok, buf = self._cv2.imencode(
                    ".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, quality]
                )
                if not ok:
                    self.report_error("JPEG encoding failed")
                    continue
                b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
                payload = {
                    MessageKeys.IMAGE.FORMAT: "jpeg",
                    MessageKeys.IMAGE.ENCODING: "base64",
                    MessageKeys.IMAGE.DATA: b64,
                    MessageKeys.IMAGE.WIDTH: frame.shape[1],
                    MessageKeys.IMAGE.HEIGHT: frame.shape[0],
                }
            else:
                payload = {
                    MessageKeys.IMAGE.FORMAT: "bgr",
                    MessageKeys.IMAGE.ENCODING: "numpy",
                    MessageKeys.IMAGE.DATA: frame,
                    MessageKeys.IMAGE.WIDTH: frame.shape[1],
                    MessageKeys.IMAGE.HEIGHT: frame.shape[0],
                }

            self._frame_count += 1
            msg = self.create_message(
                payload={MessageKeys.IMAGE.PATH: payload},
                topic="omron/frame",
                frame_count=self._frame_count,
            )
            self.send(msg)

            # Throttle
            elapsed = time.time() - t_start
            leftover = interval - elapsed
            if leftover > 0:
                time.sleep(leftover)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def _teardown_stapi(self):
        """Safely release all STAPI resources."""
        st = _get_stapi()
        if st is None:
            self._st_initialized = False
            return

        # Stop acquisition
        if self._st_datastream is not None:
            try:
                self._st_datastream.stop_acquisition()
            except Exception:
                pass
        if self._st_device is not None:
            try:
                self._st_device.acquisition_stop()
            except Exception:
                pass

        # Deregister callback
        if self._callback_handle is not None and self._st_datastream is not None:
            try:
                self._st_datastream.deregister_callback(self._callback_handle)
            except Exception:
                pass

        self._st_datastream = None
        self._st_device = None
        self._st_system = None
        self._callback_handle = None
        self._trigger_software_cmd = None

        if self._st_initialized:
            try:
                st.terminate()
            except Exception:
                pass
            self._st_initialized = False

        # Drain frame queue
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

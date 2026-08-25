"""Detection logging to CSV/JSON built on supervision's sinks."""

import logging
import os
import time
from typing import Any, Dict, Optional

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    supervision_missing_message,
    to_sv,
)

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Logs every detection to a CSV or JSON file - one row per detection per "
    "frame with bbox, class, confidence, track id, frame number and "
    "timestamp. Turns any flow into a dataset recorder."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.detections (tracked or not)")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "The message passed through, with payload.sink_file (current log path) and "
                  "payload.sink_rows (total rows written)")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Format:", "CSV (row-by-row, safe for long runs) or JSON (kept in memory, written on "
                "stop/rotate)"),
    ("Output Folder:", "Where log files go (created if missing)"),
    ("Filename Base:", "Files are named <base>_<YYYYmmdd-HHMMSS>.<ext>; a new deploy or "
                       "New File starts a fresh one"),
    ("New File:", "Close the current log and start a new timestamped file")
)
_info.add_header("Notes")
_info.add_bullets(
    ("Empty frames:", "Frames with no detections advance the frame counter but write no rows"),
    ("Roboflow:", "Pairs well with RoboflowUploadNode for dataset building")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


class SupervisionSinkNode(BaseNode):
    """Per-detection CSV/JSON logger (sv.CSVSink / sv.JSONSink)."""

    info = str(_info)
    display_name = 'SV Sink'
    icon = '🗃'
    category = 'supervision'
    color = '#7B3FA9'
    border_color = '#5C2D91'
    text_color = '#FFFFFF'

    actions = ['new_file']

    DEFAULT_CONFIG = {
        'format': 'csv',
        'path': './output',
        'filename': 'detections',
    }

    properties = [
        {
            'name': 'format',
            'label': 'Format',
            'type': 'select',
            'options': [
                {'value': 'csv', 'label': 'CSV (row per detection)'},
                {'value': 'json', 'label': 'JSON (written on stop)'},
            ],
            'default': DEFAULT_CONFIG['format'],
        },
        {
            'name': 'path',
            'label': 'Output Folder',
            'type': 'text',
            'default': DEFAULT_CONFIG['path'],
            'placeholder': DEFAULT_CONFIG['path'],
        },
        {
            'name': 'filename',
            'label': 'Filename Base',
            'type': 'text',
            'default': DEFAULT_CONFIG['filename'],
            'placeholder': DEFAULT_CONFIG['filename'],
        },
        {
            'name': 'new_file',
            'label': 'New File',
            'type': 'button',
            'action': 'new_file',
        },
    ]

    def __init__(self, node_id=None, name="sv_sink"):
        self._sink = None
        self._sink_format: Optional[str] = None
        self._sink_path: Optional[str] = None
        self._frame_index = 0
        self._rows_written = 0
        self._missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # File lifecycle
    # ------------------------------------------------------------------

    def _open_sink(self) -> bool:
        """Create the sink file lazily (first non-empty frame)."""
        sv = import_supervision()
        if sv is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            return False

        if self._sink is not None:
            return True

        fmt = 'json' if str(self.config.get('format', 'csv')).lower() == 'json' else 'csv'
        folder = str(self.config.get('path', './output') or './output')
        base = str(self.config.get('filename', 'detections') or 'detections')

        try:
            os.makedirs(folder, exist_ok=True)
            stamp = time.strftime('%Y%m%d-%H%M%S')
            path = os.path.join(folder, f"{base}_{stamp}.{fmt}")

            self._sink = sv.CSVSink(path) if fmt == 'csv' else sv.JSONSink(path)
            self._sink.open()
            self._sink_format = fmt
            self._sink_path = path
            self._rows_written = 0
            logger.info(f"SV Sink ({self.id}): logging to {path}")
            return True
        except Exception as e:
            self.report_error(f"Cannot open sink file: {e}")
            self._sink = None
            return False

    def _close_sink(self):
        if self._sink is None:
            return
        try:
            if self._sink_format == 'json':
                # JSONSink holds rows in memory and only writes here.
                self._sink.write_and_close()
            else:
                self._sink.close()
            logger.info(f"SV Sink ({self.id}): closed {self._sink_path} "
                        f"({self._rows_written} rows)")
        except Exception as e:
            self.report_error(f"Error closing sink file: {e}")
        finally:
            self._sink = None

    def new_file(self):
        """Close the current log and start a fresh timestamped one (UI action)."""
        self._close_sink()
        self._frame_index = 0
        return {'status': 'rotated'}

    def on_stop(self):
        self._close_sink()
        super().on_stop()

    def configure(self, config):
        old = {k: self.config.get(k) for k in ('format', 'path', 'filename')}
        super().configure(config)
        if self._sink is not None and any(
                old[k] != self.config.get(k) for k in old):
            # Destination changed - finish the current file, next frame opens
            # the new one.
            self._close_sink()

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def on_input(self, msg, input_index=0):
        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict):
            self.send(msg)
            return

        try:
            detections = to_sv(payload)
            if detections is None:           # supervision missing
                if not self._missing_reported:
                    self.report_error(supervision_missing_message())
                    self._missing_reported = True
                self.send(msg)
                return

            self._frame_index += 1

            # Skip empty frames: CSVSink derives its header from the first
            # append, and an empty Detections carries no class_name data key,
            # which would poison the header (or mismatch it on every frame).
            if len(detections) > 0 and self._open_sink():
                self._sink.append(detections, custom_data={
                    'frame': self._frame_index,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                })
                self._rows_written += len(detections)

            payload['sink_file'] = self._sink_path
            payload['sink_rows'] = self._rows_written
            self.send(msg)

        except Exception as e:
            logger.error(f"Error in SupervisionSinkNode: {e}", exc_info=True)
            self.report_error(f"Sink error: {e}")
            self.send(msg)

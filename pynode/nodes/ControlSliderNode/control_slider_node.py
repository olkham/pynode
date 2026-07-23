"""
Slider control node - an interactive slider on the node card that stamps its
current value onto a configurable path of every message flowing through.

Drag the slider to tune a value live and watch the effect ripple through the
downstream pipeline in real time (no redeploy). Because the node has an input
and an output and only sets one path, several can be daisy-chained to control
a compound value - e.g. four sliders writing bbox[0..3] to drive a Crop node's
detection box.
"""

from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Interactive slider. Drag it on the node card to set a value; "
               "each message passing through has that value written to the "
               "configured path and is then forwarded. Changes take effect "
               "live on the next message - no redeploy needed.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message. The slider value is written to Target Path, "
                 "then the message is forwarded."),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "The same message with Target Path set to the slider value."),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Target Path:", "Dot/bracket path to set, e.g. 'payload.threshold', "
                     "'payload.crop.x', or 'payload.detections[0].bbox[2]'. "
                     "Intermediate objects/lists are created as needed."),
    ("Min / Max:", "Slider range (e.g. 0 and 1)."),
    ("Step:", "Slider granularity (e.g. 0.01). A whole-number step emits "
              "integers, otherwise floats."),
    ("Value:", "Current/initial value; persisted with the workflow."),
    ("Label:", "Optional caption shown on the node card."),
)
_info.add_header("Tips")
_info.add_bullets(
    ("Daisy-chain:", "Wire several sliders in series to control a compound "
                     "value - 4 sliders -> a crop box, 2 -> an x/y point."),
    ("Live tuning:", "Feed a steady message stream (e.g. a camera) and the "
                     "downstream result updates as you drag."),
)


class ControlSliderNode(BaseNode):
    """Stamps an interactive slider's value onto a message path, then forwards."""

    display_name = 'Slider'
    icon = '🎚'
    category = 'function'
    color = '#D8C7ED'
    border_color = '#A98FC9'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    info = str(_info)

    ui_component = 'slider'

    # UI-triggerable action: the on-card slider POSTs its live value here.
    actions = ['set_value']

    DEFAULT_CONFIG = {
        'path': 'payload.value',
        'min': 0,
        'max': 1,
        'step': 0.01,
        'value': 0.5,
        'label': '',
        # A control shouldn't silently drop frames while tuning a pipeline.
        MessageKeys.DROP_MESSAGES: False,
    }

    properties = [
        {
            'name': 'path',
            'label': 'Target Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['path'],
            'help': "Message path to set, e.g. payload.crop.x or "
                    "payload.detections[0].bbox[2]",
        },
        {
            'name': 'min',
            'label': 'Min',
            'type': 'number',
            'default': DEFAULT_CONFIG['min'],
        },
        {
            'name': 'max',
            'label': 'Max',
            'type': 'number',
            'default': DEFAULT_CONFIG['max'],
        },
        {
            'name': 'step',
            'label': 'Step',
            'type': 'number',
            'default': DEFAULT_CONFIG['step'],
        },
        {
            'name': 'value',
            'label': 'Value',
            'type': 'number',
            'default': DEFAULT_CONFIG['value'],
        },
        {
            'name': 'label',
            'label': 'Label',
            'type': 'text',
            'default': DEFAULT_CONFIG['label'],
            'help': 'Optional caption shown on the node card',
        },
    ]

    def __init__(self, node_id=None, name="slider"):
        super().__init__(node_id, name)
        # Live value set from the UI; None until set, then falls back to config.
        self._live_value = None

    def _coerce(self, raw: Any) -> Any:
        """Parse to a number, clamp to [min, max], and pick int vs float.

        A whole-number result is returned as ``int`` so paths like a bbox
        pixel come out as ``200`` rather than ``200.0``; fractional values
        stay ``float``.
        """
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = self.get_config_float('value', 0.0)

        lo = self.get_config_float('min', 0.0)
        hi = self.get_config_float('max', 1.0)
        if lo > hi:
            lo, hi = hi, lo
        val = max(lo, min(hi, val))

        return int(val) if val.is_integer() else val

    def _active_value(self) -> Any:
        """The value to stamp: the live UI value if set, else the config value."""
        raw = self._live_value if self._live_value is not None else self.config.get('value', 0)
        return self._coerce(raw)

    def set_value(self, value: Any):
        """UI action: update the live slider value (applied to the next message)."""
        self._live_value = self._coerce(value)

    def on_start(self):
        """Seed the live value from config so it is active right after deploy."""
        super().on_start()
        self._live_value = self._coerce(self.config.get('value', 0))

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Write the current value to the target path and forward the message."""
        path = str(self.config.get('path', '')).strip()
        if path:
            try:
                self._set_nested_value(msg, path, self._active_value())
            except Exception as e:
                self.report_error(f"Slider: could not set '{path}': {e}")
        self.send(msg)

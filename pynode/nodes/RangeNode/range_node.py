"""
Range Node - scales/maps values from one range to another.
"""

import math
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Maps numeric values from one range to another using linear interpolation. Useful for scaling sensor data, normalizing values, or converting between units.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with numeric payload to scale")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with scaled payload value")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Input Min/Max:", "The expected range of input values"),
    ("Output Min/Max:", "The desired range of output values"),
    ("Clamp:", "If enabled, output is constrained to the output range"),
    ("Output Type:", "Float or Integer"),
    ("Rounding:", "How to drop the fraction: Round, Floor or Ceiling"),
    ("Decimal Places:", "Limit float precision; -1 keeps full precision"),
)
_info.add_header("Output Type")
_info.add_bullets(
    ("Float:", "Always a float, e.g. 0.5 or 200.0 (the default)."),
    ("Integer:", "Always a whole int, converted using the Rounding mode."),
)
_info.add_header("Rounding")
_info.add_text("Applies when converting to an integer, and when limiting decimal places:")
_info.add_bullets(
    ("Round:", "Nearest, halves away from zero: 2.5 -> 3, -2.5 -> -3."),
    ("Floor:", "Down towards -infinity: 2.9 -> 2, -2.1 -> -3."),
    ("Ceiling:", "Up towards +infinity: 2.1 -> 3, -2.9 -> -2."),
)
_info.add_text("Round uses half-away-from-zero, not Python's built-in banker's rounding, so 0.5 rounds to 1 rather than 0.")
_info.add_text("Rounding is applied after clamping, so an Integer output is always whole. With a fractional Output Max (e.g. 99.5) a Ceiling can therefore land just outside the range.")
_info.add_header("Example")
_info.add_text("Input range 0-100 to output range 0-1: A value of 50 becomes 0.5")
_info.add_text("Input 0-1023 to output 0-100 with Output Type = Integer and Rounding = Round: 512 becomes 50.")


class RangeNode(BaseNode):
    """
    Range Node - maps numeric values from one range to another.
    Similar to Node-RED's range node.
    """
    info = str(_info)
    display_name = 'Range'
    icon = '📊'
    category = 'function'
    color = '#87CEEB'
    border_color = '#4682B4'
    text_color = '#000000'
    input_count = 1
    output_count = 1

    DEFAULT_CONFIG = {
        'min_in': 0,
        'max_in': 1,
        'min_out': 0,
        'max_out': 100,
        'clamp': True,
        # Defaults preserve the original behaviour: a full-precision float.
        'output_type': 'float',
        'rounding': 'round',
        'decimals': -1,
        MessageKeys.DROP_MESSAGES: False
    }

    properties = [
        {
            'name': 'min_in',
            'label': 'Input Min',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_in']
        },
        {
            'name': 'max_in',
            'label': 'Input Max',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_in']
        },
        {
            'name': 'min_out',
            'label': 'Output Min',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_out']
        },
        {
            'name': 'max_out',
            'label': 'Output Max',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_out']
        },
        {
            'name': 'clamp',
            'label': 'Clamp to Output Range',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['clamp']
        },
        {
            'name': 'output_type',
            'label': 'Output Type',
            'type': 'select',
            'options': [
                {'value': 'float', 'label': 'Float (0.5, 200.0)'},
                {'value': 'int', 'label': 'Integer (whole number)'}
            ],
            'default': DEFAULT_CONFIG['output_type']
        },
        {
            'name': 'rounding',
            'label': 'Rounding',
            'type': 'select',
            'options': [
                {'value': 'round', 'label': 'Round (nearest, .5 away from zero)'},
                {'value': 'floor', 'label': 'Floor (down)'},
                {'value': 'ceil', 'label': 'Ceiling (up)'}
            ],
            'default': DEFAULT_CONFIG['rounding'],
            'help': 'Used when converting to an integer, and when limiting '
                    'decimal places.'
        },
        {
            'name': 'decimals',
            'label': 'Decimal Places',
            'type': 'number',
            'default': DEFAULT_CONFIG['decimals'],
            'min': -1,
            'max': 15,
            'step': 1,
            'help': 'Round the float to this many decimal places. -1 keeps '
                    'full precision.',
            'showIf': {'output_type': 'float'}
        }
    ]

    def __init__(self, node_id=None, name="range"):
        # BaseNode.__init__ applies DEFAULT_CONFIG; no manual configure needed.
        super().__init__(node_id, name)

    @staticmethod
    def _round_with(value: float, mode: str) -> int:
        """Convert ``value`` to a whole number using the given rounding mode.

        'round' is half-AWAY-FROM-ZERO (0.5 -> 1, -0.5 -> -1), which is what
        users expect, rather than Python's built-in banker's rounding
        (``round(0.5)`` is 0 and ``round(2.5)`` is 2).
        """
        if mode == 'floor':
            return math.floor(value)
        if mode == 'ceil':
            return math.ceil(value)
        return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)

    def _format_value(self, value: float) -> Any:
        """Apply the configured output type / rounding / precision.

        An integer output rounds straight to a whole number; otherwise the
        float is optionally rounded to ``decimals`` places.
        """
        output_type = self.config.get('output_type',
                                      self.DEFAULT_CONFIG['output_type'])
        mode = self.config.get('rounding', self.DEFAULT_CONFIG['rounding'])

        if output_type == 'int':
            return self._round_with(value, mode)

        decimals = self.get_config_int('decimals',
                                       self.DEFAULT_CONFIG['decimals'])
        if decimals >= 0:
            factor = 10.0 ** decimals
            value = self._round_with(value * factor, mode) / factor

        return float(value)

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Map payload value from input range to output range."""
        try:
            payload = msg.get(MessageKeys.PAYLOAD)
            if payload is None:
                self.report_error("No payload value to map")
                return
            value = float(payload)
            
            min_in = self.get_config_float('min_in', self.DEFAULT_CONFIG['min_in'])
            max_in = self.get_config_float('max_in', self.DEFAULT_CONFIG['max_in'])
            min_out = self.get_config_float('min_out', self.DEFAULT_CONFIG['min_out'])
            max_out = self.get_config_float('max_out', self.DEFAULT_CONFIG['max_out'])
            clamp = self.get_config_bool('clamp', self.DEFAULT_CONFIG['clamp'])
            
            # Map value
            if max_in == min_in:
                mapped = min_out
            else:
                mapped = ((value - min_in) / (max_in - min_in)) * (max_out - min_out) + min_out
            
            # Clamp if enabled
            if clamp:
                mapped = max(min(mapped, max(min_out, max_out)), min(min_out, max_out))

            # Apply the configured output type / rounding / precision last, so
            # an Integer output is always a whole number. Note this runs AFTER
            # clamping: with a fractional bound, rounding can land just outside
            # the range (Ceiling with max_out 99.5 gives 100). Formatting wins
            # over the clamp so the requested type is always honoured.
            mapped = self._format_value(mapped)

            # Preserve original message properties (like frame_count)
            # Note: send() handles deep copying, so we modify msg directly
            msg[MessageKeys.PAYLOAD] = mapped
            self.send(msg)
            
        except (ValueError, TypeError) as e:
            self.report_error(f"Invalid numeric value: {e}")

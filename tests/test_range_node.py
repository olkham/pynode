"""Tests for RangeNode - the output type / rounding / decimal-places options,
plus regressions for the existing mapping and clamping behaviour.

Nodes are driven directly (no Flask app / workflows dir, no worker threads);
the node is wired to the conftest 'sink' (synchronous on_input_direct delivery).
"""

import pytest

from pynode.nodes.RangeNode.range_node import RangeNode


def _make(sink, **config):
    node = RangeNode(name='range')
    node.configure(config)
    node.connect(sink)
    return node


def _run(sink, node, value):
    node.on_input({'payload': value})
    return sink.received[-1]['payload'] if sink.received else None


# --- existing behaviour must be unchanged by default -------------------------

def test_defaults_are_full_precision_float(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=100, min_out=0, max_out=1)
    out = _run(sink, node, 50)
    assert out == 0.5
    assert isinstance(out, float)


def test_default_output_stays_float_when_whole(node_classes):
    # A node with no output_type configured (e.g. a workflow saved before this
    # feature existed) must still emit a float, not an int.
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=1, min_out=0, max_out=100)
    out = _run(sink, node, 1)
    assert out == 100.0
    assert isinstance(out, float)


def test_clamp_still_applies(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=1, min_out=0, max_out=100, clamp=True)
    assert _run(sink, node, 5) == 100.0
    assert _run(sink, node, -5) == 0.0


# --- output type -------------------------------------------------------------

def test_output_type_int(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=1023, min_out=0, max_out=100,
                 output_type='int', rounding='round')
    out = _run(sink, node, 512)
    assert out == 50
    assert isinstance(out, int) and not isinstance(out, bool)


# --- rounding modes ----------------------------------------------------------

@pytest.mark.parametrize('mode,expected', [
    ('round', 3),
    ('floor', 2),
    ('ceil', 3),
])
def test_rounding_modes_positive(node_classes, mode, expected):
    sink = node_classes['sink'](name='sink')
    # identity mapping so the payload IS the value being rounded
    node = _make(sink, min_in=0, max_in=10, min_out=0, max_out=10,
                 output_type='int', rounding=mode, clamp=False)
    assert _run(sink, node, 2.5) == expected


@pytest.mark.parametrize('mode,expected', [
    ('round', -3),   # half away from zero
    ('floor', -3),
    ('ceil', -2),
])
def test_rounding_modes_negative(node_classes, mode, expected):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=10, min_out=0, max_out=10,
                 output_type='int', rounding=mode, clamp=False)
    assert _run(sink, node, -2.5) == expected


def test_round_is_half_away_from_zero_not_bankers(node_classes):
    # Python's built-in round() would give 0 and 2 here; users expect 1 and 3.
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=10, min_out=0, max_out=10,
                 output_type='int', rounding='round', clamp=False)
    assert _run(sink, node, 0.5) == 1
    assert _run(sink, node, 2.5) == 3
    assert _run(sink, node, 1.5) == 2


# --- decimal places ----------------------------------------------------------

def test_decimals_limits_precision(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=3, min_out=0, max_out=1,
                 output_type='float', decimals=2, rounding='round')
    assert _run(sink, node, 1) == 0.33          # 0.3333... -> 0.33


def test_decimals_uses_the_rounding_mode(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=3, min_out=0, max_out=1,
                 output_type='float', decimals=2, rounding='ceil')
    assert _run(sink, node, 1) == 0.34          # 0.3333... ceils up


def test_decimals_negative_keeps_full_precision(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=3, min_out=0, max_out=1,
                 output_type='float', decimals=-1)
    assert _run(sink, node, 1) == pytest.approx(1 / 3)


def test_decimals_ignored_for_int_output(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=10, min_out=0, max_out=10,
                 output_type='int', decimals=3, rounding='round', clamp=False)
    out = _run(sink, node, 2.7)
    assert out == 3 and isinstance(out, int)


# --- interaction with clamping ----------------------------------------------

def test_rounding_runs_after_clamp(node_classes):
    # Documented behaviour: formatting wins over the clamp, so an Integer
    # output is always whole even when the bound is fractional.
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_in=0, max_in=1, min_out=0, max_out=99.5,
                 clamp=True, output_type='int', rounding='ceil')
    out = _run(sink, node, 1)               # clamps to 99.5, then ceils
    assert out == 100 and isinstance(out, int)


# --- error handling ----------------------------------------------------------

def test_non_numeric_payload_reports_error(node_classes):
    sink = node_classes['sink'](name='sink')
    errors = []
    node = _make(sink, output_type='int')
    node.report_error = errors.append
    node.on_input({'payload': 'not a number'})
    assert errors and not sink.received


def test_none_payload_reports_error(node_classes):
    sink = node_classes['sink'](name='sink')
    errors = []
    node = _make(sink)
    node.report_error = errors.append
    node.on_input({'payload': None})
    assert errors and not sink.received


# --- config plumbing ---------------------------------------------------------

def test_default_config_applied_without_manual_configure():
    # BaseNode.__init__ applies DEFAULT_CONFIG; RangeNode no longer repeats it.
    node = RangeNode(name='range')
    for key, expected in RangeNode.DEFAULT_CONFIG.items():
        assert node.config[key] == expected


def test_declared_properties_match_default_config():
    # Every new selector must be a real, defaulted config key.
    by_name = {p['name']: p for p in RangeNode.properties}
    for key in ('output_type', 'rounding', 'decimals'):
        assert key in by_name
        assert by_name[key]['default'] == RangeNode.DEFAULT_CONFIG[key]
    for key in ('output_type', 'rounding'):
        values = [o['value'] for o in by_name[key]['options']]
        assert RangeNode.DEFAULT_CONFIG[key] in values

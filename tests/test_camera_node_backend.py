"""Tests for CameraNode's selectable OpenCV capture backend.

Only checks the pure option-building / value-to-constant-mapping logic on
the CameraNode class itself. No camera is ever opened and no capture thread
is ever started - CameraNode() is only ever instantiated, never on_start()'d.
"""

import sys

import cv2
import pytest

from pynode.nodes.CameraNode.camera_node import CameraNode
from pynode.nodes.base_node import MessageKeys

# sys.platform prefix -> normalized platform key, mirroring
# CameraNode._current_platform_key so tests can simulate each OS.
_SIMULATED_PLATFORMS = {
    'win32': 'win32',
    'linux': 'linux',
    'darwin': 'darwin',
}


def test_backend_default_is_auto():
    assert CameraNode.DEFAULT_CONFIG[MessageKeys.CAMERA.BACKEND] == 'auto'


def test_backend_property_present_with_auto_default():
    props = CameraNode.get_properties()
    backend_prop = next(p for p in props if p['name'] == MessageKeys.CAMERA.BACKEND)
    assert backend_prop['type'] == 'select'
    assert backend_prop['default'] == 'auto'
    # 'auto' must be the first option offered.
    assert backend_prop['options'][0] == {'value': 'auto', 'label': 'Auto (OpenCV default)'}


def test_options_only_contain_backends_valid_for_current_platform():
    """Every non-'auto' option must be declared for the current OS in
    _BACKEND_DEFS, and its cv2.CAP_* constant must actually exist."""
    platform_key = CameraNode._current_platform_key()
    options = CameraNode._get_backend_options()

    values = [o['value'] for o in options]
    assert values[0] == 'auto'
    assert len(values) == len(set(values)), 'no duplicate backend values'

    allowed = {'auto'}
    for value, attr, _label, platforms in CameraNode._BACKEND_DEFS:
        if (platforms is None or platform_key in platforms) and hasattr(cv2, attr):
            allowed.add(value)

    assert set(values) == allowed

    # None of the platform-restricted backends belonging to *other* OSes
    # should ever leak into the options for this platform.
    for value, _attr, _label, platforms in CameraNode._BACKEND_DEFS:
        if platforms is not None and platform_key not in platforms:
            assert value not in values


def test_backend_map_resolves_for_every_offered_option():
    """Every non-'auto' value in the options list must resolve to a real
    cv2.CAP_* integer constant via _get_backend_map()."""
    options = CameraNode._get_backend_options()
    backend_map = CameraNode._get_backend_map()

    for option in options:
        value = option['value']
        if value == 'auto':
            assert value not in backend_map  # 'auto' is handled specially, not mapped
            continue
        assert value in backend_map, f"{value!r} offered but not in backend map"
        assert isinstance(backend_map[value], int)


@pytest.mark.parametrize('simulated_platform,expected_values', [
    ('win32', {'auto', 'msmf', 'dshow', 'ffmpeg'}),
    ('linux', {'auto', 'v4l2', 'gstreamer', 'ffmpeg'}),
    ('darwin', {'auto', 'avfoundation', 'ffmpeg'}),
])
def test_options_per_simulated_platform(monkeypatch, simulated_platform, expected_values):
    """Simulate each supported OS via sys.platform so the platform-filtering
    logic is exercised regardless of which OS actually runs this test suite.

    Assumes the installed cv2 build exposes all CAP_* constants used here
    (true for standard opencv-python wheels); constants missing from a given
    build are simply skipped from the expectation.
    """
    monkeypatch.setattr(sys, 'platform', simulated_platform)
    options = CameraNode._get_backend_options()
    values = {o['value'] for o in options}

    # Only expect constants that actually exist on this cv2 build.
    expected = {'auto'}
    for value, attr, _label, platforms in CameraNode._BACKEND_DEFS:
        if value in expected_values and hasattr(cv2, attr):
            expected.add(value)

    assert values == expected

    # And the mapping resolves for each simulated option too.
    backend_map = CameraNode._get_backend_map()
    for value in values - {'auto'}:
        assert value in backend_map
        assert isinstance(backend_map[value], int)


def test_camera_node_instantiates_without_opening_camera():
    """Sanity check: constructing the node must not touch any hardware."""
    node = CameraNode(node_id='cam-test', name='cam')
    try:
        assert node.camera is None
        assert node.running is False
        assert node.config.get(MessageKeys.CAMERA.BACKEND) == 'auto' or \
            MessageKeys.CAMERA.BACKEND not in node.config
    finally:
        # No thread/camera was ever started, but on_close() is a harmless no-op guard.
        node.on_close()

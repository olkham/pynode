"""Tests for OpenVINO device detection, dropdown option building, and the
config -> OpenVINO device-string translation.

openvino / ultralytics are NOT required: openvino is simulated via
sys.modules monkeypatching, and the module under test must import cleanly
without either package installed.
"""

import sys
import types

import pytest

from pynode.nodes.InferenceNode.InferenceEngine import device_detection


class _FakeCore:
    """Stand-in for openvino.Core with a configurable device list."""

    devices = ['CPU']

    @property
    def available_devices(self):
        return list(type(self).devices)


def _install_fake_openvino(monkeypatch, devices):
    """Install a fake 'openvino' module exposing Core().available_devices."""
    fake = types.ModuleType('openvino')
    _FakeCore.devices = devices
    fake.Core = _FakeCore
    monkeypatch.setitem(sys.modules, 'openvino', fake)


def _remove_openvino(monkeypatch):
    """Make 'from openvino import Core' (and openvino.runtime) fail."""
    monkeypatch.setitem(sys.modules, 'openvino', None)
    monkeypatch.setitem(sys.modules, 'openvino.runtime', None)


@pytest.fixture(autouse=True)
def _reset_device_cache(monkeypatch):
    """Each test starts (and leaves) with an empty enumeration cache."""
    monkeypatch.setattr(device_detection, '_device_cache', None)
    yield


class TestGetOpenvinoDevices:
    def test_multi_gpu_enumeration(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        devices, detected = device_detection.get_openvino_devices()
        assert detected is True
        assert devices == ['CPU', 'GPU.0', 'GPU.1']

    def test_fallback_when_openvino_missing(self, monkeypatch):
        _remove_openvino(monkeypatch)
        devices, detected = device_detection.get_openvino_devices()
        assert detected is False
        assert devices == device_detection.FALLBACK_DEVICES

    def test_result_is_cached(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU'])
        devices, detected = device_detection.get_openvino_devices()
        assert (devices, detected) == (['CPU', 'GPU'], True)

        # Change the underlying device list; the cached result must persist
        _FakeCore.devices = ['CPU']
        devices, detected = device_detection.get_openvino_devices()
        assert devices == ['CPU', 'GPU']

        # refresh=True re-enumerates
        devices, detected = device_detection.get_openvino_devices(refresh=True)
        assert devices == ['CPU']

    def test_enumeration_failure_falls_back(self, monkeypatch):
        fake = types.ModuleType('openvino')

        class _BrokenCore:
            def __init__(self):
                raise RuntimeError('driver exploded')

        fake.Core = _BrokenCore
        monkeypatch.setitem(sys.modules, 'openvino', fake)

        devices, detected = device_detection.get_openvino_devices()
        assert detected is False
        assert devices == device_detection.FALLBACK_DEVICES


class TestIntelDeviceOptions:
    def test_multi_gpu_options(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        options = device_detection.get_intel_device_options()
        assert options == [
            {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
            {'value': 'intel:gpu.0', 'label': 'Intel GPU 0 (OpenVINO)'},
            {'value': 'intel:gpu.1', 'label': 'Intel GPU 1 (OpenVINO)'},
        ]
        # No NPU detected -> no NPU option
        assert not any('npu' in o['value'] for o in options)

    def test_single_gpu_label_has_no_index(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU'])
        options = device_detection.get_intel_device_options()
        assert {'value': 'intel:gpu', 'label': 'Intel GPU (OpenVINO)'} in options

    def test_single_indexed_gpu_label_has_no_index(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0'])
        options = device_detection.get_intel_device_options()
        assert {'value': 'intel:gpu.0', 'label': 'Intel GPU (OpenVINO)'} in options

    def test_npu_included_only_when_detected(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU', 'NPU'])
        options = device_detection.get_intel_device_options()
        assert {'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'} in options

    def test_cpu_only_system(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU'])
        options = device_detection.get_intel_device_options()
        assert options == [{'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'}]

    def test_fallback_options_match_legacy_dropdown(self, monkeypatch):
        _remove_openvino(monkeypatch)
        options = device_detection.get_intel_device_options()
        assert options == [
            {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
            {'value': 'intel:gpu', 'label': 'Intel GPU (OpenVINO)'},
            {'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'},
        ]

    def test_inference_node_dropdown_includes_detected_devices(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        from pynode.nodes.InferenceNode.inference_node import InferenceNode

        values = [o['value'] for o in InferenceNode._get_device_options()]
        assert 'cpu' in values
        assert 'intel:cpu' in values
        assert 'intel:gpu.0' in values
        assert 'intel:gpu.1' in values
        assert 'intel:npu' not in values


class TestResolveIntelDevice:
    def test_plain_intel_gpu_resolves_to_first_detected_gpu(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.resolve_intel_device('intel:gpu') == 'intel:gpu.0'

    def test_case_insensitive(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.resolve_intel_device('INTEL:GPU') == 'intel:gpu.0'

    def test_explicit_index_is_preserved(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.resolve_intel_device('intel:gpu.1') == 'intel:gpu.1'

    def test_no_detection_leaves_device_unchanged(self, monkeypatch):
        _remove_openvino(monkeypatch)
        assert device_detection.resolve_intel_device('intel:gpu') == 'intel:gpu'

    def test_no_gpu_detected_leaves_device_unchanged(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU'])
        assert device_detection.resolve_intel_device('intel:gpu') == 'intel:gpu'

    def test_non_intel_devices_untouched(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        for dev in ('cpu', 'cuda:0', 'intel:cpu', 'intel:npu'):
            assert device_detection.resolve_intel_device(dev) == dev


class TestUltralyticsNodeDevices:
    """UltralyticsNode dropdown option-building and device normalization.

    The node module imports torch at module level, so these tests skip when
    torch is absent. No model is ever loaded (instantiation is lazy).
    """

    def _node_class(self):
        pytest.importorskip('torch')
        from pynode.nodes.UltralyticsNode.ultralytics_node import UltralyticsNode
        return UltralyticsNode

    def test_dropdown_includes_detected_intel_gpus(self, monkeypatch):
        UltralyticsNode = self._node_class()
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])

        values = [o['value'] for o in UltralyticsNode._get_device_options()]
        assert 'cpu' in values
        assert 'intel:cpu' in values
        assert 'intel:gpu.0' in values
        assert 'intel:gpu.1' in values
        assert 'intel:npu' not in values

        # And the same options flow through the property schema
        props = UltralyticsNode.get_properties()
        device_prop = next(p for p in props if p['name'] == 'device')
        prop_values = [o['value'] for o in device_prop['options']]
        assert 'intel:gpu.0' in prop_values and 'intel:gpu.1' in prop_values

    def test_dropdown_fallback_without_openvino(self, monkeypatch):
        UltralyticsNode = self._node_class()
        _remove_openvino(monkeypatch)

        values = [o['value'] for o in UltralyticsNode._get_device_options()]
        assert 'cpu' in values
        assert 'intel:cpu' in values
        assert 'intel:gpu' in values
        assert 'intel:npu' in values

    def test_node_resolves_configured_device(self, monkeypatch):
        UltralyticsNode = self._node_class()
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])

        node = UltralyticsNode(node_id='y1', name='yolo')
        node.config['device'] = 'intel:gpu'
        assert node._resolve_configured_device() == 'intel:gpu.0'

        node.config['device'] = 'intel:gpu.1'
        assert node._resolve_configured_device() == 'intel:gpu.1'

        node.config['device'] = 'cpu'
        assert node._resolve_configured_device() == 'cpu'

    def test_node_resolution_unchanged_without_detection(self, monkeypatch):
        UltralyticsNode = self._node_class()
        _remove_openvino(monkeypatch)

        node = UltralyticsNode(node_id='y1', name='yolo')
        node.config['device'] = 'intel:gpu'
        assert node._resolve_configured_device() == 'intel:gpu'

    def test_model_or_device_change_marks_for_reload(self, monkeypatch):
        UltralyticsNode = self._node_class()
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])

        node = UltralyticsNode(node_id='y1', name='yolo')
        node._model_loaded = True  # simulate a loaded model

        node.configure({'device': 'intel:gpu.1'})
        assert node._model_loaded is False

        node._model_loaded = True
        node.configure({'model': 'yolo11n.pt'})
        assert node._model_loaded is False

        # Unrelated config changes must NOT force a reload
        node._model_loaded = True
        node.configure({'confidence': '0.5'})
        assert node._model_loaded is True


class TestUltralyticsEngineDeviceNormalization:
    """End-to-end check of the engine's device normalization.

    Runs only when ultralytics is installed (it is not a test dependency);
    the OpenVINO device list is pinned via the detection cache so the test
    is hardware-independent.
    """

    def test_engine_resolves_devices(self, monkeypatch):
        pytest.importorskip('ultralytics')
        monkeypatch.setattr(
            device_detection, '_device_cache', (['CPU', 'GPU.0', 'GPU.1'], True))
        from pynode.nodes.InferenceNode.InferenceEngine.engines.ultralytics_engine import (
            UltralyticsEngine,
        )

        eng = UltralyticsEngine(device='intel:gpu')
        assert eng.device == 'intel:gpu.0'
        assert eng.use_openvino is True

        eng = UltralyticsEngine(device='GPU.1')
        assert eng.device == 'intel:gpu.1'
        assert eng.use_openvino is True

        eng = UltralyticsEngine(device='cuda:0')
        assert eng.device == 'cuda:0'
        assert eng.use_openvino is False


class TestToOpenvinoDeviceName:
    def test_indexed_gpu(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.to_openvino_device_name('intel:gpu.1') == 'GPU.1'

    def test_plain_gpu_resolves_to_first_gpu(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.to_openvino_device_name('intel:gpu') == 'GPU.0'

    def test_plain_gpu_without_detection_stays_gpu(self, monkeypatch):
        _remove_openvino(monkeypatch)
        assert device_detection.to_openvino_device_name('intel:gpu') == 'GPU'

    def test_cpu(self, monkeypatch):
        _remove_openvino(monkeypatch)
        assert device_detection.to_openvino_device_name('intel:cpu') == 'CPU'

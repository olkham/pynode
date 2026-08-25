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
    names = {}

    @property
    def available_devices(self):
        return list(type(self).devices)

    def get_property(self, device, prop):
        # KeyError for unnamed devices mirrors a property query failing;
        # device_detection must tolerate it per-device.
        return type(self).names[device]


def _install_fake_openvino(monkeypatch, devices, names=None):
    """Install a fake 'openvino' module exposing Core().available_devices."""
    fake = types.ModuleType('openvino')
    _FakeCore.devices = devices
    _FakeCore.names = names or {}
    fake.Core = _FakeCore
    monkeypatch.setitem(sys.modules, 'openvino', fake)


def _install_fake_torch(monkeypatch, cuda_available, device_count=1):
    """Install a fake 'torch' module with a configurable CUDA state."""
    fake = types.ModuleType('torch')
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: cuda_available,
        device_count=lambda: device_count,
    )
    monkeypatch.setitem(sys.modules, 'torch', fake)


def _remove_torch(monkeypatch):
    """Make 'import torch' fail."""
    monkeypatch.setitem(sys.modules, 'torch', None)


def _remove_openvino(monkeypatch):
    """Make 'from openvino import Core' (and openvino.runtime) fail."""
    monkeypatch.setitem(sys.modules, 'openvino', None)
    monkeypatch.setitem(sys.modules, 'openvino.runtime', None)


@pytest.fixture(autouse=True)
def _reset_device_cache(monkeypatch):
    """Each test starts (and leaves) with an empty enumeration cache."""
    monkeypatch.setattr(device_detection, '_device_cache', None)
    monkeypatch.setattr(device_detection, '_device_names', {})
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


class TestIntelGpuVendorFiltering:
    """OpenVINO's GPU plugin enumerates every OpenCL GPU, so a machine with
    an NVIDIA card lists it as e.g. GPU.1 - it must not be offered or
    targeted as an OpenVINO device."""

    NAMES = {
        'CPU': '13th Gen Intel(R) Core(TM) i9-13900K',
        'GPU.0': 'Intel(R) UHD Graphics 770 (iGPU)',
        'GPU.1': 'NVIDIA TITAN RTX (dGPU)',
    }

    def test_non_intel_gpu_excluded_from_options(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'], self.NAMES)
        values = [o['value'] for o in device_detection.get_intel_device_options()]
        assert 'intel:gpu.0' in values
        assert 'intel:gpu.1' not in values

    def test_label_carries_device_name(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'], self.NAMES)
        options = device_detection.get_intel_device_options()
        gpu0 = next(o for o in options if o['value'] == 'intel:gpu.0')
        assert 'UHD Graphics 770' in gpu0['label']

    def test_unnamed_gpus_are_kept(self, monkeypatch):
        # Names not queryable (older openvino): keep every GPU, as before
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        values = [o['value'] for o in device_detection.get_intel_device_options()]
        assert 'intel:gpu.0' in values and 'intel:gpu.1' in values

    def test_resolve_skips_non_intel_gpu(self, monkeypatch):
        names = {'GPU.0': 'NVIDIA TITAN RTX (dGPU)',
                 'GPU.1': 'Intel(R) Arc(TM) A770 Graphics (dGPU)'}
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'], names)
        assert device_detection.resolve_intel_device('intel:gpu') == 'intel:gpu.1'


class TestValidateDevice:
    def test_cpu_always_valid(self, monkeypatch):
        _remove_openvino(monkeypatch)
        _remove_torch(monkeypatch)
        assert device_detection.validate_device('cpu') == ('cpu', None)
        assert device_detection.validate_device('intel:cpu') == ('intel:cpu', None)

    def test_cuda_valid_when_present(self, monkeypatch):
        _install_fake_torch(monkeypatch, cuda_available=True, device_count=2)
        assert device_detection.validate_device('cuda:1') == ('cuda:1', None)

    def test_cuda_index_out_of_range_uses_first(self, monkeypatch):
        _install_fake_torch(monkeypatch, cuda_available=True, device_count=1)
        device, warning = device_detection.validate_device('cuda:1')
        assert device == 'cuda:0'
        assert warning and 'cuda:1' in warning

    def test_cuda_on_cpu_only_torch_falls_back(self, monkeypatch):
        _install_fake_torch(monkeypatch, cuda_available=False)
        device, warning = device_detection.validate_device('cuda:0')
        assert device == 'cpu'
        assert warning and 'CPU-only' in warning

    def test_cuda_without_torch_falls_back(self, monkeypatch):
        _remove_torch(monkeypatch)
        device, warning = device_detection.validate_device('cuda:0')
        assert device == 'cpu'
        assert warning and 'PyTorch is not installed' in warning

    def test_intel_gpu_present_is_valid(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'])
        assert device_detection.validate_device('intel:gpu.1') == ('intel:gpu.1', None)

    def test_plain_intel_gpu_resolves_without_warning(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0'])
        assert device_detection.validate_device('intel:gpu') == ('intel:gpu.0', None)

    def test_missing_intel_gpu_index_substitutes_existing(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0'])
        device, warning = device_detection.validate_device('intel:gpu.1')
        assert device == 'intel:gpu.0'
        assert warning and 'intel:gpu.1' in warning

    def test_index_now_owned_by_non_intel_gpu_substitutes(self, monkeypatch):
        # Hardware-change scenario: GPU.1 used to be an Intel card; after a
        # GPU swap the index belongs to an NVIDIA card OpenVINO enumerates
        # via OpenCL but cannot compile models for.
        names = {'GPU.0': 'Intel(R) UHD Graphics 770 (iGPU)',
                 'GPU.1': 'NVIDIA TITAN RTX (dGPU)'}
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0', 'GPU.1'], names)
        device, warning = device_detection.validate_device('intel:gpu.1')
        assert device == 'intel:gpu.0'
        assert warning and 'NVIDIA TITAN RTX' in warning

    def test_no_intel_gpu_falls_back_to_cuda(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU'])
        _install_fake_torch(monkeypatch, cuda_available=True, device_count=1)
        device, warning = device_detection.validate_device('intel:gpu.0')
        assert device == 'cuda:0'
        assert warning

    def test_no_intel_gpu_no_cuda_falls_back_to_cpu(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU'])
        _remove_torch(monkeypatch)
        device, warning = device_detection.validate_device('intel:gpu')
        assert device == 'cpu'
        assert warning

    def test_missing_npu_falls_back(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'GPU.0'])
        _remove_torch(monkeypatch)
        device, warning = device_detection.validate_device('intel:npu')
        assert device == 'cpu'
        assert warning

    def test_present_npu_is_valid(self, monkeypatch):
        _install_fake_openvino(monkeypatch, ['CPU', 'NPU'])
        assert device_detection.validate_device('intel:npu') == ('intel:npu', None)

    def test_unverifiable_devices_pass_through(self, monkeypatch):
        _remove_openvino(monkeypatch)
        assert device_detection.validate_device('intel:gpu.1') == ('intel:gpu.1', None)
        assert device_detection.validate_device('mps') == ('mps', None)
        assert device_detection.validate_device('') == ('', None)


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

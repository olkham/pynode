"""OpenVINO device detection and device-string translation helpers.

This module must stay importable when openvino (and ultralytics/torch) are
NOT installed: enumeration is attempted lazily on first use and falls back to
a static device list when openvino is unavailable or enumeration fails.

Device naming background:

- ``openvino.Core().available_devices`` returns names like
  ``['CPU', 'GPU', 'NPU']`` (single GPU) or ``['CPU', 'GPU.0', 'GPU.1']``
  (multiple GPUs).
- PyNode/Ultralytics config values use the ``intel:<device>`` form
  (``intel:gpu``, ``intel:gpu.1`` ...). Ultralytics strips the ``intel:``
  prefix and passes the uppercased remainder to OpenVINO, so on a multi-GPU
  system a plain ``intel:gpu`` becomes ``GPU`` which is NOT in
  ``available_devices`` and Ultralytics silently falls back to ``AUTO``.
  :func:`resolve_intel_device` fixes that by resolving ``intel:gpu`` to the
  first detected Intel GPU (e.g. ``intel:gpu.0``).
- The GPU plugin enumerates every OpenCL-capable GPU, including non-Intel
  ones it cannot compile models for (an NVIDIA card can appear as
  ``GPU.1`` -> ``NVIDIA TITAN RTX (dGPU)``), so GPU entries are filtered by
  their ``FULL_DEVICE_NAME`` before being offered as OpenVINO targets.

Workflows carry the device string of the machine they were built on, which
may not exist after a hardware change or an export/import.
:func:`validate_device` checks a configured device against the hardware
actually present and returns the closest usable substitute plus a warning.
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Static fallback used when openvino is not importable or enumeration fails.
# It mirrors the historical hardcoded dropdown (CPU/GPU/NPU) so behavior is
# unchanged on systems without openvino.
FALLBACK_DEVICES: List[str] = ['CPU', 'GPU', 'NPU']

# Cache: (devices, detected). ``detected`` is False when the fallback list is
# in use. Enumeration can be slow, so it runs once (lazily) per process.
_device_cache: Optional[Tuple[List[str], bool]] = None

# FULL_DEVICE_NAME per enumerated device (e.g. 'GPU.0' -> 'Intel(R) UHD
# Graphics 770 (iGPU)'). Populated alongside _device_cache; empty when names
# could not be queried or the fallback list is in use.
_device_names: Dict[str, str] = {}


def _enumerate_openvino_devices() -> Optional[Tuple[List[str], Dict[str, str]]]:
    """Return ``(devices, names)`` from OpenVINO, or None if unavailable."""
    try:
        from openvino import Core  # type: ignore
    except ImportError:
        try:
            # Older openvino releases expose Core under openvino.runtime
            from openvino.runtime import Core  # type: ignore
        except ImportError:
            return None
    try:
        core = Core()
        devices = list(core.available_devices)
    except Exception as e:
        logger.warning(f"OpenVINO device enumeration failed: {e}")
        return None
    names: Dict[str, str] = {}
    for device in devices:
        try:
            names[device] = str(core.get_property(device, 'FULL_DEVICE_NAME'))
        except Exception:
            pass
    return devices, names


def get_openvino_devices(refresh: bool = False) -> Tuple[List[str], bool]:
    """Return ``(devices, detected)``.

    ``devices`` is e.g. ``['CPU', 'GPU.0', 'GPU.1']`` when openvino is
    available, otherwise :data:`FALLBACK_DEVICES`. ``detected`` says whether
    real enumeration succeeded. The result is cached after the first call.
    """
    global _device_cache, _device_names
    if refresh or _device_cache is None:
        result = _enumerate_openvino_devices()
        if result and result[0]:
            devices, names = result
            _device_cache = (devices, True)
            _device_names = names
        else:
            _device_cache = (list(FALLBACK_DEVICES), False)
            _device_names = {}
    devices, detected = _device_cache
    return list(devices), detected


def get_openvino_device_names() -> Dict[str, str]:
    """Return FULL_DEVICE_NAME per device (may be empty), e.g.
    ``{'GPU.0': 'Intel(R) UHD Graphics 770 (iGPU)'}``."""
    get_openvino_devices()  # ensure enumeration has been attempted
    return dict(_device_names)


def _gpu_devices(devices: List[str]) -> List[str]:
    """Filter GPU entries ('GPU', 'GPU.0', ...) preserving enumeration order."""
    return [d for d in devices if d == 'GPU' or d.startswith('GPU.')]


def _intel_gpu_devices(devices: List[str]) -> List[str]:
    """GPU entries that are actually Intel GPUs.

    OpenVINO's GPU plugin enumerates every OpenCL GPU, so on a machine with
    an NVIDIA card ``available_devices`` can contain e.g. ``GPU.1`` ->
    ``NVIDIA TITAN RTX (dGPU)`` even though the plugin cannot compile models
    for it. Devices whose FULL_DEVICE_NAME is unknown are kept (older
    openvino releases and the static fallback list carry no names).
    """
    names = get_openvino_device_names()
    intel_gpus = []
    for device in _gpu_devices(devices):
        name = names.get(device)
        if name is None or 'intel' in name.lower():
            intel_gpus.append(device)
    return intel_gpus


def get_cuda_devices() -> List[str]:
    """Return ``['cuda:0', ...]`` via torch, or ``[]`` when torch is missing,
    is a CPU-only build, or no NVIDIA GPU is present."""
    try:
        import torch  # type: ignore
    except ImportError:
        return []
    try:
        if not torch.cuda.is_available():
            return []
        return [f'cuda:{i}' for i in range(torch.cuda.device_count())]
    except Exception as e:
        logger.warning(f"CUDA device enumeration failed: {e}")
        return []


def get_intel_device_options() -> List[Dict[str, str]]:
    """Build the Intel OpenVINO entries for the hardware dropdown.

    - Intel CPU is always offered.
    - One entry per detected Intel GPU (non-Intel GPUs that OpenVINO merely
      enumerates via OpenCL are excluded); if there is exactly one GPU the
      label has no index. Values keep the device suffix (``intel:gpu.0``
      etc.) and labels carry the FULL_DEVICE_NAME when known.
    - NPU is offered only when present in the device list (the static
      fallback list includes it, preserving the old dropdown when openvino
      is not installed).
    """
    devices, _detected = get_openvino_devices()
    names = get_openvino_device_names()

    options: List[Dict[str, str]] = [
        {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
    ]

    gpus = _intel_gpu_devices(devices)
    for gpu in gpus:
        if len(gpus) == 1:
            label = 'Intel GPU (OpenVINO)'
        elif '.' in gpu:
            label = f'Intel GPU {gpu.split(".", 1)[1]} (OpenVINO)'
        else:
            label = 'Intel GPU (OpenVINO)'
        if names.get(gpu):
            label = f'{label} - {names[gpu]}'
        options.append({
            'value': f'intel:{gpu.lower()}',
            'label': label,
        })

    if any(d == 'NPU' or d.startswith('NPU.') for d in devices):
        options.append({'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'})

    return options


def resolve_intel_device(device: str) -> str:
    """Resolve a plain ``intel:gpu`` to the first detected GPU.

    ``intel:gpu`` (any case) becomes e.g. ``intel:gpu.0`` on multi-GPU
    systems so the exact device - not AUTO - is targeted. Anything else
    (``intel:gpu.1``, ``intel:cpu``, ``cuda:0``, ``cpu`` ...) is returned
    unchanged, and when detection is unavailable the input is returned as-is
    (backward compatible with saved workflows on systems without openvino).
    """
    if not isinstance(device, str) or device.lower() != 'intel:gpu':
        return device

    devices, detected = get_openvino_devices()
    if not detected:
        return device

    gpus = _intel_gpu_devices(devices)
    if not gpus:
        return device
    return f'intel:{gpus[0].lower()}'


def validate_device(device: str) -> Tuple[str, Optional[str]]:
    """Check a configured device against the hardware present on THIS machine.

    Saved workflows carry device strings from whatever machine they were
    built on; after a hardware change or an export/import the configured
    device may simply not exist here. Returns ``(usable_device, warning)``:
    ``warning`` is None when the device is usable as-is (modulo the plain
    ``intel:gpu`` -> ``intel:gpu.N`` resolution). When it is not, the closest
    present device is substituted - another Intel GPU if one exists, else the
    first CUDA GPU, else CPU - and the warning explains the switch so the
    user can fix the config. Devices that cannot be verified (openvino not
    installed, unrecognized strings) are returned unchanged.
    """
    if not isinstance(device, str) or not device:
        return device, None
    lower = device.lower()

    if lower in ('cpu', 'intel:cpu'):
        return device, None

    if lower.startswith('cuda') or lower.isdigit():
        cuda_devices = get_cuda_devices()
        if not cuda_devices:
            try:
                import torch  # type: ignore  # noqa: F401
                reason = ('CUDA is not available - no NVIDIA GPU, or a '
                          'CPU-only PyTorch build is installed')
            except ImportError:
                reason = 'PyTorch is not installed'
            return 'cpu', (f"Configured device '{device}' is not usable "
                           f"({reason}). Falling back to 'cpu'.")
        index = 0
        if lower.isdigit():
            index = int(lower)
        elif ':' in lower:
            try:
                index = int(lower.split(':', 1)[1])
            except ValueError:
                index = 0
        if index >= len(cuda_devices):
            return cuda_devices[0], (
                f"Configured device '{device}' not found (only "
                f"{len(cuda_devices)} CUDA device(s) present). Using "
                f"'{cuda_devices[0]}' instead.")
        return device, None

    if lower.startswith('intel:'):
        devices, detected = get_openvino_devices()
        if not detected:
            # Cannot verify without openvino enumeration; keep the existing
            # pass-through behavior for saved workflows.
            return device, None
        target = lower.split(':', 1)[1].upper()

        if target == 'GPU' or target.startswith('GPU.'):
            gpus = _intel_gpu_devices(devices)
            if target in gpus:
                return device, None
            if target == 'GPU' and gpus:
                # Plain 'intel:gpu' -> first Intel GPU (not a hardware change)
                return f'intel:{gpus[0].lower()}', None
            if gpus:
                substitute = f'intel:{gpus[0].lower()}'
                names = get_openvino_device_names()
                extra = ''
                if target in _gpu_devices(devices) and names.get(target):
                    # The index exists but points at a non-Intel OpenCL GPU
                    extra = (f" ('{target}' is {names[target]}, which "
                             "OpenVINO cannot target)")
                return substitute, (
                    f"Configured device '{device}' is not available on this "
                    f"machine{extra}. Using '{substitute}' instead.")
            fallback = _fallback_device()
            return fallback, (
                f"Configured device '{device}' is not available on this "
                f"machine (no Intel GPU detected by OpenVINO). Falling back "
                f"to '{fallback}'.")

        if target == 'NPU' or target.startswith('NPU.'):
            if any(d == 'NPU' or d.startswith('NPU.') for d in devices):
                return device, None
            fallback = _fallback_device()
            return fallback, (
                f"Configured device '{device}' is not available on this "
                f"machine (no Intel NPU detected). Falling back to "
                f"'{fallback}'.")

        return device, None

    return device, None


def _fallback_device() -> str:
    """Best present device to substitute for an absent one: the first CUDA
    GPU when torch can use one, otherwise CPU."""
    cuda_devices = get_cuda_devices()
    return cuda_devices[0] if cuda_devices else 'cpu'


def to_openvino_device_name(device: str) -> str:
    """Translate a config value to the OpenVINO device name Ultralytics uses.

    ``intel:gpu.1`` -> ``GPU.1``; ``intel:gpu`` -> first detected GPU (e.g.
    ``GPU.0``) or ``GPU`` when detection is unavailable; non-``intel:``
    values are just uppercased (matching Ultralytics' behavior of
    ``device.split(':')[1].upper()``).
    """
    resolved = resolve_intel_device(device)
    if isinstance(resolved, str) and resolved.lower().startswith('intel:'):
        return resolved.split(':', 1)[1].upper()
    return str(resolved).upper()

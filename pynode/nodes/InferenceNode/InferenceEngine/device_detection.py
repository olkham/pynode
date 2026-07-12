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
  first detected GPU (e.g. ``intel:gpu.0``).
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


def _enumerate_openvino_devices() -> Optional[List[str]]:
    """Return the real OpenVINO device list, or None if unavailable."""
    try:
        from openvino import Core  # type: ignore
    except ImportError:
        try:
            # Older openvino releases expose Core under openvino.runtime
            from openvino.runtime import Core  # type: ignore
        except ImportError:
            return None
    try:
        return list(Core().available_devices)
    except Exception as e:
        logger.warning(f"OpenVINO device enumeration failed: {e}")
        return None


def get_openvino_devices(refresh: bool = False) -> Tuple[List[str], bool]:
    """Return ``(devices, detected)``.

    ``devices`` is e.g. ``['CPU', 'GPU.0', 'GPU.1']`` when openvino is
    available, otherwise :data:`FALLBACK_DEVICES`. ``detected`` says whether
    real enumeration succeeded. The result is cached after the first call.
    """
    global _device_cache
    if refresh or _device_cache is None:
        devices = _enumerate_openvino_devices()
        if devices:
            _device_cache = (devices, True)
        else:
            _device_cache = (list(FALLBACK_DEVICES), False)
    devices, detected = _device_cache
    return list(devices), detected


def _gpu_devices(devices: List[str]) -> List[str]:
    """Filter GPU entries ('GPU', 'GPU.0', ...) preserving enumeration order."""
    return [d for d in devices if d == 'GPU' or d.startswith('GPU.')]


def get_intel_device_options() -> List[Dict[str, str]]:
    """Build the Intel OpenVINO entries for the hardware dropdown.

    - Intel CPU is always offered.
    - One entry per detected GPU; if there is exactly one GPU the label has
      no index. Values keep the device suffix (``intel:gpu.0`` etc.).
    - NPU is offered only when present in the device list (the static
      fallback list includes it, preserving the old dropdown when openvino
      is not installed).
    """
    devices, _detected = get_openvino_devices()

    options: List[Dict[str, str]] = [
        {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
    ]

    gpus = _gpu_devices(devices)
    if len(gpus) == 1:
        options.append({
            'value': f'intel:{gpus[0].lower()}',
            'label': 'Intel GPU (OpenVINO)',
        })
    else:
        for gpu in gpus:
            if '.' in gpu:
                index = gpu.split('.', 1)[1]
                label = f'Intel GPU {index} (OpenVINO)'
            else:
                label = 'Intel GPU (OpenVINO)'
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

    gpus = _gpu_devices(devices)
    if not gpus:
        return device
    return f'intel:{gpus[0].lower()}'


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

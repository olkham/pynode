# ultralytics_node imports torch at module level. Guard it so lightweight
# submodules (e.g. model_paths, which has no heavy imports) stay importable in
# a core-only install without torch/ultralytics. When the vision deps are
# missing the node is simply unavailable (node auto-discovery already tolerates
# this via its own ImportError handling).
try:
    from .ultralytics_node import UltralyticsNode
    __all__ = ['UltralyticsNode']
except ImportError:
    __all__ = []


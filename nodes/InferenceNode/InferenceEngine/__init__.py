from .engines.base_engine import BaseInferenceEngine
from .inference_engine_factory import InferenceEngineFactory

# Don't import specific engines directly - let the factory auto-discover them
# This prevents import errors when optional dependencies (like geti_sdk) aren't installed

# Import result conversion utilities
# from .result_converters import (
#     ultralytics_to_geti,
#     geti_to_ultralytics,
#     # normalize_result_format,
#     extract_detections_summary,
#     create_rectangle,
#     GETI_SDK_AVAILABLE
# )

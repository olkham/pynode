"""
PyNode - A Node-RED-like Visual Workflow System with Python Backend
"""

# Tune CPU thread pools before heavy libraries (torch/OpenMP) initialise, so
# the OMP_WAIT_POLICY change takes effect. See pynode._perf for rationale.
from pynode._perf import configure_inference_threads

configure_inference_threads()

from pynode.workflow_engine import WorkflowEngine

__version__ = '0.2.0'
__all__ = ['WorkflowEngine']

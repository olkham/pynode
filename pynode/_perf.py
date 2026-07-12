"""CPU thread-pool tuning for GPU-backed inference.

The heavy model math runs on the GPU (CUDA / OpenVINO), but every frame still
triggers small CPU-side pre/post-processing ops around it: letterbox resize,
NMS, tensor -> numpy conversions, and result drawing. PyTorch and OpenCV each
default their thread pool to span *every* core, and OpenMP's default wait
policy is ACTIVE (busy-spin), so those pools keep spinning between the tiny
per-frame ops and peg the CPU even though the GPU does the real work.

These ops are latency-bound, not throughput-bound, so a wide pool buys nothing
and only adds spin overhead. We cap the pools and disable the busy-spin.

Call configure_inference_threads() as early as possible - before torch/OpenMP
initialise - so the OMP_WAIT_POLICY change takes effect.

Overridable via PYNODE_INFERENCE_THREADS (e.g. set it higher when you actually
run a plain .pt model on the CPU *device* and want torch to use more cores;
GPU / OpenVINO inference is unaffected by this cap, which only touches the
light pre/post-processing).
"""

import logging
import os

logger = logging.getLogger(__name__)

# Pre/post-processing ops are small and latency-bound; a handful of threads is
# plenty and avoids the all-cores busy-spin that dominates CPU during GPU runs.
_DEFAULT_THREADS = 4


def _thread_cap() -> int:
    override = os.environ.get("PYNODE_INFERENCE_THREADS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            logger.warning(
                "Invalid PYNODE_INFERENCE_THREADS=%r; using default", override
            )
    cpu = os.cpu_count() or _DEFAULT_THREADS
    return min(_DEFAULT_THREADS, cpu)


def configure_inference_threads() -> None:
    """Cap torch/OpenCV CPU thread pools and disable OpenMP busy-spin."""
    # Must be set before the OpenMP runtime initialises (i.e. before torch is
    # imported) for the worker threads to stop busy-spinning between ops.
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

    cap = _thread_cap()

    try:
        import torch

        torch.set_num_threads(cap)
    except Exception as e:  # torch may be optional / not importable yet
        logger.debug("Could not cap torch threads: %s", e)

    try:
        import cv2

        cv2.setNumThreads(cap)
    except Exception as e:
        logger.debug("Could not cap OpenCV threads: %s", e)

"""Nodes built on the ``supervision`` library.

Tracking comes from Roboflow's ``trackers`` package (``supervision`` 0.31 removed
its built-in ByteTrack) and re-identification from ``reid``.

``supervision`` ships in the ``[vision]`` extra, so it is absent from a core
install. These nodes still register and appear in the palette without it - they
report a clear error and pass messages through untouched. Shared conversion
helpers live in :mod:`pynode.nodes.supervision_utils`.
"""

from .supervision_annotate_node import SupervisionAnnotateNode
from .supervision_filter_node import SupervisionFilterNode
from .supervision_line_counter_node import SupervisionLineCounterNode
from .supervision_reid_node import SupervisionReIDNode
from .supervision_sink_node import SupervisionSinkNode
from .supervision_smoother_node import SupervisionSmootherNode
from .supervision_tracker_node import SupervisionTrackerNode
from .supervision_zone_node import SupervisionZoneNode

__all__ = [
    'SupervisionAnnotateNode',
    'SupervisionFilterNode',
    'SupervisionLineCounterNode',
    'SupervisionReIDNode',
    'SupervisionSinkNode',
    'SupervisionSmootherNode',
    'SupervisionTrackerNode',
    'SupervisionZoneNode',
]

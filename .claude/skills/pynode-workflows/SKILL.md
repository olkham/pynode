---
name: pynode-workflows
description: Build, edit and validate PyNode workflow JSON files (nodes + connections) that users can import via the GUI or REST API. Use when asked to create example flows, generate a workflow, wire nodes together, or debug a workflow definition.
---

# Building PyNode Workflows

A PyNode workflow is a JSON document describing nodes and the connections
between them. The GUI's **Import** button (hamburger menu) accepts a flat
workflow file and loads it into a **new tab** named after the file. The same
document can be POSTed to `/api/workflow`.

## Workflow file format

```json
{
  "nodes": [
    {
      "id": "inject_1",
      "type": "InjectNode",
      "name": "Every 2s",
      "config": { "props": [{"property": "payload", "value": "hi", "valueType": "str"}], "repeat": "2" },
      "x": 80, "y": 80
    }
  ],
  "connections": [
    { "source": "inject_1", "target": "debug_1", "sourceOutput": 0, "targetInput": 0 }
  ]
}
```

Rules:
- `type` is the **Python class name** of the node (e.g. `InjectNode`, `MqttOutNode`).
  Unknown types import as disabled placeholder nodes — always validate.
- `id` is any unique string. Use readable slugs (`camera_1`, `yolo_1`).
- `enabled` is optional (default `true`). `x`/`y` are canvas pixels; space
  columns ~260px apart (80, 340, 600, 860, 1120), rows ~140px apart.
- `sourceOutput`/`targetInput` are 0-based port indexes.
- Config values are lenient: many nodes read numbers from strings
  (`"confidence": "0.25"`) — copy the conventions below exactly.
- The on-disk `workflows/workflow.json` uses a different multi-workflow
  wrapper (`{version, activeWorkflow, workflows: [...]}`); **never** write that
  file directly — import through the GUI or API instead.

## Message conventions

Messages are dicts in Node-RED style: `payload`, `topic`, `_msgid`, plus extras.
- Images travel at `msg.payload.image` as a numpy BGR array (or JPEG bytes if a
  source has `encode_jpeg: true`). Downstream nodes locate it via their
  `image_path` config, default `payload.image`.
- Detections travel at `msg.payload.detections`: a list of
  `{"bbox": [x1,y1,x2,y2], "bbox_format": "xyxy", "class_name": str,
  "class_id": int, "confidence": float}`, with `payload.detection_count` and
  `payload.bbox_format` alongside.
- `MqttOutNode` publishes `msg.payload`; **`msg.topic` overrides the node's
  configured topic** — don't set a `topic` in InjectNode when a downstream
  MQTT-out node should control the topic.

## Node catalog (config keys verified against source)

### Core / logic
| Type | Ports in→out | Config (defaults) |
|---|---|---|
| `InjectNode` | 0→1 | `props`: list of `{property: "payload", value, valueType: str\|num\|bool\|json\|date\|env}` (dot paths OK, e.g. `payload.count`); `topic`: str; `once`: seconds (str, empty=off); `repeat`: seconds (str, empty=off). Manual trigger button built in. |
| `DebugNode` | 1→0 | `console`: bool; `complete`: `"payload"` (default) or `"msg"` for whole message; `drop_messages`: bool |
| `FunctionNode` | 1→N | `func`: Python source (body of a function receiving `msg`, `node`, `time`; must `return msg` / a list for multiple outputs / `None` to drop); `outputs`: int (default 1). Full builtins and `import` are available inside the body. |
| `SwitchNode` | 1→N | `property`: dot path (`payload`, `payload.count`); `checkall`: bool; `rules`: list of `{operator, value, valueType}` — **rule index = output index**. Operators: `eq neq lt lte gt gte between contains matches true false null nnull else`. |
| `ChangeNode` | 1→1 | `rules`: list of `{type: set\|delete\|change\|move, path: "msg.payload...", value, valueType}` |
| `GateNode` | 1→1 | `{}` — passes messages only while enabled; toggled live from its card |
| `DelayNode` | 1→1 | `mode`: `delay`\|`delay_count`\|`rate`; `timeout`: secs (delay mode); `rate` + `rate_time`: msgs per secs; `rate_drop`: `drop`\|`queue` |
| `CounterNode` | 1→1 | `initial_value`: "0"; `increment`: "1"; `retain_payload`: "false" |
| `RateProbeNode` | 1→1 | `window_size`: seconds (float) — passes msgs through, shows msg/s |

### Vision
| Type | Ports | Config |
|---|---|---|
| `CameraNode` | 0→1 | `device_index`: 0; `fps`: 30; `width`: 640; `height`: 480; `encode_jpeg`: false; `jpeg_quality`: 75 |
| `VideoReaderNode` | 0→1 | `source`: path (upload via node properties in GUI); `fps`: 0 (=native); `loop`: bool; `jpeg_quality`: 80 |
| `UltralyticsNode` | 1→1 | `model`: "yolo11n.pt" (auto-downloads); `confidence`: "0.25"; `iou`: "0.45"; `draw_results`: "true"/"false"; `max_det`: "300"; `include_image`: true; `include_predictions`: true; `drop_messages`: "true" (keep on!); `device`: "cpu" (portable) or `cuda:0`/`intel:gpu` |
| `LabelFilterNode` | 1→2 | `labels`: "person, car" (comma list); `match_mode`: `any`\|`all`; `case_sensitive`: false; `filter_detections`: true (strips non-matching detections); `detections_path`: "payload.detections". **Output 0 = matched, output 1 = unmatched.** |
| `ConfidenceFilterNode` | 1→2 | `threshold_source`: `manual`\|`msg`; `threshold`: 0.5; `detections_path`: "payload.detections"; `confidence_field`: "confidence". **Output 0 = ≥ threshold, output 1 = < threshold.** |
| `ImageViewerNode` | 1→0 | `width`: 320; `height`: 240; `image_path`: "payload.image"; `drop_messages`: true |
| `VideoWriterNode` | 1→0 | `path`: "./output"; `filename`: "video_{counter}"; `codec`: `mp4v`\|`avc1`\|`xvid`...; `framerate`: 30.0; `width`/`height`; `auto_resolution`: bool (match input); `clip_length`: 0 (=unlimited); `naming_mode`: "counter"; `counter_digits`: 4 |

Other vision nodes: `DrawPredictionsNode`, `CropNode`, `TrackerNode`,
`ImageFormatNode`, `SliceNode`, `BBoxMetricsNode`, `PolygonMetricsNode`,
`InferenceNode` (multi-backend), `FrameSourceNode` (multi-source camera lib) —
read their `DEFAULT_CONFIG`/`properties` in `pynode/nodes/<Name>/` before use.

### Network
| Type | Ports | Config |
|---|---|---|
| `MqttInNode` | 0→1 | `serviceId`: broker id from mqtt_services.json; `topic`: subscribe topic (wildcards `#`/`+` OK); `qos`: "0" |
| `MqttOutNode` | 1→0 | `serviceId`; `topic`: publish topic; `qos`: "0"; `retain`: "false" |

MQTT brokers are **services** stored in `mqtt_services.json` next to the
workflow data (managed in the GUI via the node's Broker dropdown → add). A
workflow referencing an unknown `serviceId` imports fine but the node reports
"No MQTT broker configured" until the user picks a broker.

Also available: `WebhookNode`, `RESTEndpointNode`, `mDNSNode`.

## FunctionNode authoring rules

The `func` string is the **body** of `def user_function(msg, node, time)` —
top-level `return` is required to emit. `msg` is a deep copy. Imports work
inside the body (`import cv2`, `import numpy as np`, `import random`).
Return a list to fan out across `outputs`; `None` drops the message.

Example — blur every detection bbox in-place:

```python
import cv2
import numpy as np
p = msg.get('payload') or {}
img = p.get('image')
dets = p.get('detections') or []
if not isinstance(img, np.ndarray):
    return msg
h, w = img.shape[:2]
for d in dets:
    bbox = d.get('bbox') or []
    if len(bbox) != 4:
        continue
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1 = max(0, min(x1, w - 1)); x2 = max(x1 + 1, min(x2, w))
    y1 = max(0, min(y1, h - 1)); y2 = max(y1 + 1, min(y2, h))
    k = max(9, ((x2 - x1) // 4)) | 1
    p['image'][y1:y2, x1:x2] = cv2.GaussianBlur(img[y1:y2, x1:x2], (k, k), 0)
return msg
```

When embedding code in workflow JSON, join lines with `\n` and keep
indentation exact.

## Loading a workflow

- **GUI (import)**: hamburger menu → *Import* → choose the `.json` file → it
  opens as a new tab → press *Deploy* to activate.
- **GUI (bundled examples)**: hamburger menu → *Examples* → pick one. These are
  the files in `pynode/static/examples/`, served statically and listed via
  `pynode/static/examples/manifest.json`. **When adding a new bundled example,
  drop the `.json` in that folder and add an entry to `manifest.json`** (id,
  file, title, description, requires) or it won't appear in the menu.
- **API**: `POST /api/workflow` with the JSON body imports into the active
  workflow (add `?workflow=<id>` to target another; `X-API-Key` header if the
  server has an API key). `GET /api/workflow` exports the current one —
  building a flow in the GUI and exporting it is the best way to learn configs.

## Validating a workflow file (do this for every file you produce)

Run a sandboxed import — never against the real server or the repo's
`workflows/` dir (a leaked test once destroyed real data; see
tests/conftest.py):

```python
import json, tempfile, os
from pynode.server import create_app  # use a venv with the vision extras

td = tempfile.mkdtemp()
app = create_app({'WORKFLOWS_DIR': os.path.join(td, 'wf'),
                  'WORKFLOW_FILE': os.path.join(td, 'wf', 'workflow.json'),
                  'UPLOAD_BASE_DIR': os.path.join(td, 'up'), 'TESTING': True})
client = app.test_client()
data = json.load(open('pynode/static/examples/01-hello-world.json'))
r = client.post('/api/workflow', json=data)
assert r.status_code == 201, r.get_json()
manager = app.extensions['workflow_manager']
with manager.state_lock:
    eng = next(iter(manager.working_engines.values()))
    unknown = [n.type for n in eng.nodes.values() if getattr(n, '_is_unknown_node', False)]
assert not unknown, f"unknown node types: {unknown}"
manager.shutdown()
```

Checklist:
- every connection's `source`/`target` id exists; port indexes < the node's
  `input_count`/`output_count`
- node `type` strings match class names exactly (case-sensitive)
- vision chains keep `drop_messages` on for slow consumers (YOLO, viewers)
- prefer `device: "cpu"` and auto-downloading models (`yolo11n.pt`) so flows
  run anywhere; note anything machine-specific (camera index, broker IP) in an
  accompanying README

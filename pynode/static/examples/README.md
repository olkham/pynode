# Example Workflows

Ten ready-to-load workflows that teach PyNode from "hello world" to a complete
vision → logic → MQTT pipeline. No code changes needed — each file is pure
workflow definition.

These files are bundled with the app and served at `/examples/`. The list the
editor shows is driven by [`manifest.json`](manifest.json) — add a file **and**
a manifest entry to make a new example appear in the menu.

## How to load an example

1. Start PyNode (`pynode`) and open the editor at `http://localhost:5000`.
2. Open the **☰ menu** (top right) and hover **Examples**.
3. Click an example — it opens as a **new tab**.
4. Press **Deploy** to activate it, then interact with the nodes (Inject
   buttons, Gate toggles, viewers, the Debug panel at the bottom).

You can also load any `.json` here via **☰ menu → Import**. The reverse works
too: build something in the editor and use **Export** to save it as JSON —
comparing an export against these files is a great way to learn the format.

## The examples

Roughly in order of complexity:

| # | File | What it teaches |
|---|------|-----------------|
| 1 | `01-hello-world.json` | The smallest flow: Inject → Debug. Press the inject button, watch the Debug panel. Messages have `payload` and `topic`. |
| 2 | `02-function-transform.json` | FunctionNode: write Python against `msg`, return it to send. Inject fires every 2s; the function reshapes the payload into a dict. |
| 3 | `03-switch-routing.json` | Routing: a random number is sent to output 0 (≥ 0.5) or the `else` output. ChangeNode tags the high path's `topic`. Rule order = output order. |
| 4 | `04-flow-control.json` | Back-pressure tools: Gate (toggle flow live), Delay in rate-limit mode (10 msgs in → 1 msg/s out), RateProbe and Counter to observe it. |
| 5 | `05-webcam-viewer.json` | First vision flow: CameraNode → ImageViewerNode. Images travel at `payload.image`. |
| 6 | `06-webcam-yolo.json` | Object detection: YOLO annotates the frame for a viewer, while a FunctionNode branch summarises detections (`payload.detections`) for the Debug panel. |
| 7 | `07-blur-people.json` | **Detect → filter a class → act on it**: YOLO (drawing off) → LabelFilter keeps only `person` boxes → FunctionNode Gaussian-blurs each bbox → viewer. The filter's second output shows frames with no person. |
| 8 | `08-video-yolo-recorder.json` | Video I/O: VideoReader (⚠ pick a video file in its properties first) → YOLO → live preview + VideoWriter saving annotated video to `./output`. |
| 9 | `09-mqtt-pub-sub.json` | MQTT loopback: Inject publishes every 5s, a subscriber on `pynode/demo/#` receives it back. Uses the broker configured in the node's Broker dropdown. |
| 10 | `10-person-alert-mqtt.json` | Capstone: camera → YOLO → ConfidenceFilter (≥ 0.6) → LabelFilter (`person`) → alert builder → Switch (only when count > 0) → rate-limited MQTT alert + debug log. |

## Prerequisites by example

- **1–4**: nothing beyond a core install.
- **5–7, 10**: a webcam on device index 0 (change `device_index` in the camera
  node's properties if needed), plus the vision extra
  (`pip install "pynode-flow[vision]"`). `yolo11n.pt` auto-downloads on first
  run; first inference is slow while the model loads. `device` is set to `cpu`
  everywhere for portability — switch it to your GPU in the YOLO node's
  properties for more FPS.
- **8**: vision extra + a video file. Open the VideoReader node's properties
  and upload/select a file before deploying.
- **9–10**: the mqtt extra (`pip install "pynode-flow[mqtt]"`) and a reachable
  MQTT broker. The examples reference a broker service (`192.168.1.241` in the
  dev setup); if the MQTT nodes report "No MQTT broker configured", open the
  node's properties and pick or create your broker in the **MQTT Broker**
  dropdown. Verify externally with e.g.
  `mosquitto_sub -h <broker> -t 'pynode/#' -v`.

## Things to try after loading

- **3**: change the Switch threshold, or add a third rule (`between` → new output).
- **4**: toggle the Gate off and on; watch the Counter freeze and resume.
- **7**: change the LabelFilter to `car`, `dog`, or `person, car`; swap
  `cv2.GaussianBlur` for pixelation (resize down + up) in the function.
- **10**: point the MQTT topic at your home-automation broker and you have a
  real presence alert; raise `rate_time` to reduce alert frequency.

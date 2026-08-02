# Example Workflows

Sixteen ready-to-load workflows that teach PyNode from "hello world" to a
complete vision → logic → MQTT pipeline. No code changes needed — each file is
pure workflow definition.

These files are bundled with the app and served at `/examples/`. The list the
editor shows is driven by [`manifest.json`](manifest.json) — add a file **and**
a manifest entry to make a new example appear in the menu.

## How to load an example

1. Start PyNode (`pynode`) and open the editor at `http://localhost:5000`.
2. Open the **☰ menu** (top right) and hover **Examples**.
3. Click an example — it opens as a **new tab**.
4. Press **Deploy** to activate it, then interact with the nodes (Inject
   buttons, Gate toggles, sliders, viewers, and the **🐛 Debug** tab in the
   right sidebar).

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
| 11 | `16-socket-bridge.json` | Networking: the two halves of a bridge to another system — Inject → UDP Out (sends on 7401), and UDP In (listens on 7402) → Debug. The halves are deliberately **not** connected to each other; something else sits in the middle. Copy the matching Node-RED flow from either node's **Information** panel. |
| 12 | `17-slider-crop.json` | Live UI controls: four Slider nodes drive x/y/width/height of a CropNode against an uploaded image, previewed in an ImageViewer as you drag. |
| 13 | `18-track-trace.json` | Object tracking: VideoReader (⚠ pick a video file first) → YOLO (drawing off) → **SV Tracker** assigns persistent IDs → **SV Annotate** draws boxes, `#id` labels and trace ribbons colored per track. |
| 14 | `19-line-counter.json` | Line counting: tracked objects crossing a virtual line are counted in/out (**SV Line Counter**), one event message per crossing to the Debug panel. Draw the line on a live frame via ✏ in the node's properties. |
| 15 | `20-zone-occupancy.json` | Region monitoring: a polygon zone (**SV Polygon Zone**) counts who is inside, flags detections `in_zone`, and emits enter/exit events. Draw the zone on a live webcam frame via ✏. |
| 16 | `21-annotator-gallery.json` | Visualization styles: one uploaded image → YOLO → six **SV Annotate** nodes side by side (classic, rounded, corners, broadcast ellipse, privacy blur, pixelate). A live reference for what each annotator looks like. |

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
- **11**: core install, plus **a peer on the other end** — on its own the Debug
  node stays silent, because the flow is one side of a bridge. Either import
  the Node-RED flow from a socket node's Information panel, or point the UDP
  Out node's Port at `7402` to loop it straight back into the UDP In node on
  the same machine.
- **12**: core install; select an image in the ImageUpload node's properties
  before deploying, then drag the sliders.
- **13**: vision extra + a video file (open the VideoReader's properties and
  pick one). Best with moving people or vehicles so the traces have somewhere
  to go. Press the tracker's **Reset** button when the video loops.
- **14**: vision extra + a video file with things crossing a line (street
  footage is ideal). After deploying, open the line node's properties and press
  **✏ Draw on frame** to drag the counting line onto the actual scene — it
  applies live and resets the counts.
- **15**: vision extra + webcam. Deploy, then draw the zone on a live frame
  (**✏ Draw on frame** in the zone node's properties, right-click to undo a
  corner). Walk in and out of the zone and watch enter/exit events in Debug.
- **16**: vision extra; upload an image with people/objects in the ImageUpload
  node's properties. All six styles update together at 5 fps, so property
  changes (colors, thickness, label content) show up live.
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

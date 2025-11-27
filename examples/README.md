# PyNode Example Workflows

This directory contains example Python scripts that demonstrate how to use PyNode workflows programmatically without the UI.

## Examples

### 1. `camera_workflow.py` - Simple Camera Display

A basic example that captures frames from your webcam and displays them in an OpenCV window.

**Features:**
- Camera capture at 30 FPS
- Real-time display using OpenCV
- Configurable resolution (default: 640x480)

**Usage:**
```bash
python examples/camera_workflow.py
```

**Controls:**
- Press `q` in the display window to quit
- Press `Ctrl+C` in terminal to quit

### 2. `camera_yolo_workflow.py` - Camera with YOLO Object Detection

An advanced example that captures camera frames, performs real-time YOLO object detection, and displays the annotated results.

**Features:**
- Camera capture at 30 FPS
- YOLOv8 object detection (uses yolov8n.pt - nano model)
- Real-time bounding boxes and labels
- FPS counter
- Detection count display
- Configurable confidence threshold

**Usage:**
```bash
python examples/camera_yolo_workflow.py
```

**Requirements:**
- OpenCV (opencv-python)
- Ultralytics YOLO (ultralytics)
- First run will download the YOLOv8n model (~6MB)

**Performance Notes:**
- Default configuration uses CPU
- For GPU acceleration, change `'device': 'cpu'` to `'device': 'cuda'` in the code
- YOLOv8n is the fastest model but less accurate
- For better accuracy, try yolov8s.pt, yolov8m.pt, or yolov8l.pt

**Controls:**
- Press `q` in the display window to quit
- Press `Ctrl+C` in terminal to quit

## Creating Custom Nodes

Both examples include a custom `DisplayNode` that demonstrates how to create your own nodes. You can extend this pattern to create any custom processing nodes:

```python
class MyCustomNode(BaseNode):
    display_name = 'My Node'
    icon = '⚡'
    category = 'function'
    input_count = 1
    output_count = 1
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        # Process incoming message
        payload = msg.get('payload')
        
        # Do your processing
        result = self.process(payload)
        
        # Send output
        output_msg = self.create_message(payload=result)
        self.send(output_msg)
```

## Workflow Structure

All examples follow this pattern:

1. **Import modules** - Import the workflow engine and node types
2. **Register node types** - Register all available node types with the engine
3. **Create nodes** - Instantiate nodes with configuration
4. **Connect nodes** - Wire nodes together to create the workflow
5. **Start workflow** - Begin execution
6. **Run loop** - Keep the script running
7. **Stop workflow** - Clean shutdown

## Tips

- The first YOLO inference may take a few seconds to load the model
- Adjust the camera FPS based on your processing pipeline speed
- Use JPEG encoding (`encode_jpeg: True`) for better performance
- Monitor the FPS counter to optimize your pipeline
- For production use, add error handling and logging

## Troubleshooting

**Camera not found:**
- Check your `camera_index` (try 0, 1, 2)
- Make sure no other application is using the camera
- On Linux, check camera permissions

**Low FPS:**
- Reduce camera resolution
- Use a faster YOLO model (yolov8n.pt)
- Enable GPU if available (`device: 'cuda'`)
- Reduce camera FPS to match processing speed

**YOLO errors:**
- Install ultralytics: `pip install ultralytics`
- Model will auto-download on first run
- Check internet connection for model download

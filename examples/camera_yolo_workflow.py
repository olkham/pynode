"""
Advanced example workflow that captures camera frames, performs YOLO object detection,
and displays the annotated results using OpenCV.
This example runs without the UI - it creates nodes programmatically.
"""

import sys
import os
import time
import cv2
import numpy as np
import base64
from typing import Dict, Any

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow_engine import WorkflowEngine
from base_node import BaseNode
import nodes


class DisplayNode(BaseNode):
    """
    Custom node to display images in an OpenCV window with FPS counter.
    """
    display_name = 'Display'
    icon = '🖥️'
    category = 'output'
    input_count = 1
    output_count = 0
    
    def __init__(self, node_id=None, name="display"):
        super().__init__(node_id, name)
        self.window_name = f"Display - {name}"
        self.frame_count = 0
        self.start_time = time.time()
        self.fps = 0
        
    def on_start(self):
        """Create the display window when workflow starts."""
        super().on_start()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        self.start_time = time.time()
        self.frame_count = 0
        print(f"[{self.name}] Display window created")
    
    def on_stop(self):
        """Close the display window when workflow stops."""
        super().on_stop()
        cv2.destroyWindow(self.window_name)
        print(f"[{self.name}] Display window closed")
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming image messages and display them.
        """
        payload = msg.get('payload')
        if payload is None:
            return
        
        image = None
        
        # Handle different image formats
        if isinstance(payload, dict):
            img_format = payload.get('format')
            encoding = payload.get('encoding')
            data = payload.get('data')
            
            if img_format == 'jpeg' and encoding == 'base64':
                try:
                    img_bytes = base64.b64decode(data)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception as e:
                    print(f"[{self.name}] Error decoding: {e}")
                    return
        elif isinstance(payload, np.ndarray):
            image = payload
        
        if image is not None:
            # Calculate FPS
            self.frame_count += 1
            elapsed = time.time() - self.start_time
            if elapsed > 1.0:
                self.fps = self.frame_count / elapsed
                self.frame_count = 0
                self.start_time = time.time()
            
            # Draw FPS and detection info on frame
            display_image = image.copy()
            cv2.putText(display_image, f"FPS: {self.fps:.1f}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Display detection count if available
            detection_count = msg.get('detection_count', 0)
            if detection_count > 0:
                cv2.putText(display_image, f"Detections: {detection_count}", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            try:
                cv2.imshow(self.window_name, display_image)
                cv2.waitKey(1)
            except Exception as e:
                print(f"[{self.name}] Error displaying: {e}")


def main():
    """
    Main function to create and run the camera + YOLO workflow.
    """
    print("=" * 70)
    print("Camera + YOLO Object Detection Workflow - OpenCV Example")
    print("=" * 70)
    print()
    
    # Create workflow engine
    engine = WorkflowEngine()
    
    # Register available node types
    print("Registering node types...")
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)
    engine.register_node_type(DisplayNode)
    print(f"Registered {len(engine.node_types)} node types")
    print()
    
    # Create nodes
    print("Creating nodes...")
    
    # Camera node
    camera = engine.create_node(
        'CameraNode',
        node_id='camera_1',
        name='Webcam',
        config={
            'camera_index': 0,
            'fps': 30,
            'width': 640,
            'height': 480,
            'encode_jpeg': True
        }
    )
    print(f"  ✓ Created {camera.name} (Camera)")
    
    # YOLO detection node
    yolo = engine.create_node(
        'UltralyticsNode',
        node_id='yolo_1',
        name='YOLO Detector',
        config={
            'model': 'yolov8n.pt',      # Fastest model
            'device': 'cpu',            # Use CPU (change to 'cuda' for GPU)
            'confidence': '0.5',        # Confidence threshold
            'iou': '0.45',              # IoU threshold
            'draw_results': 'true',     # Draw bounding boxes
            'max_det': '300'
        }
    )
    print(f"  ✓ Created {yolo.name} (YOLO)")
    print(f"      Model: yolov8n.pt")
    print(f"      Device: cpu")
    print(f"      Confidence: 0.5")
    
    # Display node
    display = engine.create_node(
        'DisplayNode',
        node_id='display_1',
        name='Detection Display'
    )
    print(f"  ✓ Created {display.name} (Display)")
    print()
    
    # Connect nodes: Camera → YOLO → Display
    print("Connecting nodes...")
    engine.connect_nodes('camera_1', 'yolo_1', output_index=0, input_index=0)
    print(f"  ✓ {camera.name} → {yolo.name}")
    
    engine.connect_nodes('yolo_1', 'display_1', output_index=0, input_index=0)
    print(f"  ✓ {yolo.name} → {display.name}")
    print()
    
    # Start the workflow
    print("Starting workflow...")
    engine.start()
    print("  ✓ Workflow running")
    print()
    
    print("=" * 70)
    print("Object detection is now running!")
    print("The camera feed with YOLO detections is displaying in the window")
    print()
    print("Controls:")
    print("  - Press 'q' in the window to stop")
    print("  - Press Ctrl+C here to stop")
    print("=" * 70)
    print()
    print("Note: First inference may take a few seconds while loading the model...")
    print()
    
    try:
        # Keep the script running and check for quit key
        while True:
            key = cv2.waitKey(100) & 0xFF
            if key == ord('q'):
                print("\n'q' key pressed, stopping...")
                break
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, stopping...")
    
    finally:
        # Stop the workflow
        print("\nStopping workflow...")
        engine.stop()
        cv2.destroyAllWindows()
        print("Workflow stopped")
        print()
        
        # Print statistics
        stats = engine.get_workflow_stats()
        print("Workflow Statistics:")
        print(f"  Total nodes: {stats['total_nodes']}")
        print(f"  Total connections: {stats['total_connections']}")
        print()
        print("Done!")


if __name__ == '__main__':
    main()

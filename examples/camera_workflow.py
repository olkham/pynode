"""
Example workflow that captures camera frames and displays them using OpenCV.
This example runs without the UI - it creates nodes programmatically,
connects them, and displays the output in an OpenCV window.
"""

import sys
import os
import time
import cv2
import numpy as np
import base64
from typing import Dict, Any

from pynode.workflow_engine import WorkflowEngine
from pynode.nodes.base_node import BaseNode
from pynode import nodes


class DisplayNode(BaseNode):
    """
    Custom node to display camera frames in an OpenCV window.
    This node receives image messages and displays them.
    """
    display_name = 'Display'
    icon = '🖥️'
    category = 'output'
    input_count = 1
    output_count = 0
    
    def __init__(self, node_id=None, name="display"):
        super().__init__(node_id, name)
        self.window_name = f"Display - {name}"
        self.last_frame = None
        self.should_close = False
    
    def on_start(self):
        """Create the display window when workflow starts."""
        super().on_start()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        print(f"[{self.name}] Display window created")
    
    def on_stop(self):
        """Close the display window when workflow stops."""
        super().on_stop()
        self.should_close = True
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
                    # Decode base64 JPEG
                    img_bytes = base64.b64decode(data)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception as e:
                    print(f"[{self.name}] Error decoding JPEG: {e}")
                    return
            elif img_format == 'bgr' and encoding == 'raw':
                try:
                    # Convert list back to numpy array
                    image = np.array(data, dtype=np.uint8)
                except Exception as e:
                    print(f"[{self.name}] Error converting raw BGR: {e}")
                    return
        elif isinstance(payload, np.ndarray):
            image = payload
        
        if image is not None:
            self.last_frame = image
            
            # Display the frame
            try:
                cv2.imshow(self.window_name, image)
                cv2.waitKey(1)  # Process window events
            except Exception as e:
                print(f"[{self.name}] Error displaying frame: {e}")


def main():
    """
    Main function to create and run the camera display workflow.
    """
    print("=" * 60)
    print("Camera Display Workflow - OpenCV Example")
    print("=" * 60)
    print()
    
    # Create workflow engine
    engine = WorkflowEngine()
    
    # Register available node types
    print("Registering node types...")
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)
    
    # Register our custom DisplayNode
    engine.register_node_type(DisplayNode)
    print(f"Registered {len(engine.node_types)} node types")
    print()
    
    # Create nodes
    print("Creating nodes...")
    
    # Camera node - captures frames from webcam
    camera = engine.create_node(
        'CameraNode',
        node_id='camera_1',
        name='Webcam',
        config={
            'camera_index': 0,      # First camera
            'fps': 30,              # 30 FPS
            'width': 640,           # Resolution
            'height': 480,
            'encode_jpeg': True     # Encode as JPEG for efficiency
        }
    )
    print(f"  ✓ Created {camera.name} (Camera)")
    
    # Display node - shows frames in OpenCV window
    display = engine.create_node(
        'DisplayNode',
        node_id='display_1',
        name='Main Display'
    )
    print(f"  ✓ Created {display.name} (Display)")
    print()
    
    # Connect nodes
    print("Connecting nodes...")
    engine.connect_nodes('camera_1', 'display_1', output_index=0, input_index=0)
    print(f"  ✓ Connected {camera.name} → {display.name}")
    print()
    
    # Start the workflow
    print("Starting workflow...")
    engine.start()
    print("  ✓ Workflow running")
    print()
    
    print("=" * 60)
    print("Camera feed is now displaying in OpenCV window")
    print("Press 'q' in the window or Ctrl+C here to stop")
    print("=" * 60)
    print()
    
    try:
        # Keep the script running and check for quit key
        while True:
            # Check if user pressed 'q' in the OpenCV window
            key = cv2.waitKey(100) & 0xFF
            if key == ord('q'):
                print("\n'q' key pressed, stopping...")
                break
            
            # Small sleep to prevent high CPU usage
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

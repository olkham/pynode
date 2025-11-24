"""
Node implementations for the PyNode workflow system.
Auto-generated - do not edit manually.
"""

import os
import importlib
from pathlib import Path

# Auto-discover node types
_node_classes = []
_node_names = []

# Get the nodes directory
_nodes_dir = Path(__file__).parent

# Scan for node folders (folders containing a Python file with a class ending in 'Node')
for item in _nodes_dir.iterdir():
    if item.is_dir() and not item.name.startswith('_') and not item.name.startswith('.'):
        # Convert folder name to snake_case module name
        # e.g., "CameraNode" -> "camera_node"
        folder_name = item.name
        module_name = ''.join(['_' + c.lower() if c.isupper() else c for c in folder_name]).lstrip('_')
        
        # Try to import the module
        try:
            module_path = f".{folder_name}.{module_name}"
            module = importlib.import_module(module_path, package='nodes')
            
            # Look for a class with the same name as the folder
            if hasattr(module, folder_name):
                node_class = getattr(module, folder_name)
                _node_classes.append(node_class)
                _node_names.append(folder_name)
                # Dynamically add to module globals
                globals()[folder_name] = node_class
        except (ImportError, AttributeError) as e:
            print(f"Warning: Could not import {folder_name}: {e}")
            continue


def get_all_node_types():
    """
    Get a list of all available node types.
    
    Returns:
        List of node classes
    """
    return _node_classes


__all__ = _node_names

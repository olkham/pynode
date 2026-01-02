"""
Node implementations for the PyNode workflow system.
Auto-generated - do not edit manually.
"""

import importlib
import inspect
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Auto-discover node types
_node_classes = []
_node_names = []

# Get the nodes directory
_nodes_dir = Path(__file__).parent


def _discover_node_classes_in_module(module, folder_name):
    """
    Find all BaseNode subclasses in a module.
    Returns list of (class_name, class_object) tuples.
    """
    from pynode.nodes.base_node import BaseNode
    
    found_classes = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        # Check if it's a BaseNode subclass (but not BaseNode itself)
        if (issubclass(obj, BaseNode) and 
            obj is not BaseNode and 
            name.endswith('Node') and
            obj.__module__.startswith(f'pynode.nodes.{folder_name}')):
            found_classes.append((name, obj))
    
    return found_classes


def _try_import_from_init(folder_name):
    """Try to import from __init__.py"""
    try:
        module = importlib.import_module(f'.{folder_name}', package='pynode.nodes')
        return _discover_node_classes_in_module(module, folder_name)
    except ImportError as e:
        # Suppress missing dependency errors silently for cleaner output
        if "No module named" not in str(e):
            logger.warning(f"Error importing {folder_name}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error importing {folder_name}: {e}")
        return []


def _try_import_python_files(folder_path, folder_name):
    """Try to import from individual Python files in the folder"""
    found_classes = []
    
    for py_file in folder_path.glob('*.py'):
        if py_file.name.startswith('_') or py_file.name == '__init__.py':
            continue
        
        module_name = py_file.stem
        try:
            module = importlib.import_module(f'.{folder_name}.{module_name}', package='pynode.nodes')
            found_classes.extend(_discover_node_classes_in_module(module, folder_name))
        except ImportError:
            # Suppress missing dependency errors silently
            continue
        except Exception:
            continue
    
    return found_classes


# Scan for node folders
for item in _nodes_dir.iterdir():
    if not item.is_dir() or item.name.startswith('_') or item.name.startswith('.'):
        continue
    
    folder_name = item.name
    found_classes = []
    
    # Strategy 1: Try importing from __init__.py
    found_classes = _try_import_from_init(folder_name)
    
    # Strategy 2: If nothing found, scan individual Python files
    if not found_classes:
        found_classes = _try_import_python_files(item, folder_name)
    
    # Register all found node classes
    for class_name, node_class in found_classes:
        if class_name not in _node_names:  # Avoid duplicates
            _node_classes.append(node_class)
            _node_names.append(class_name)
            globals()[class_name] = node_class


def get_all_node_types():
    """
    Get a list of all available node types.
    
    Returns:
        List of node classes
    """
    return _node_classes


__all__ = _node_names # type: ignore

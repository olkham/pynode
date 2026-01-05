"""
Error node - captures and displays error messages from any node in the workflow.
Automatically receives error events and displays them in the debug panel.
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info

# Build info content
_info = Info()
_info.add_text("Captures and displays error messages from any node in the workflow.")
_info.add_text("Unlike debug nodes that need to be wired, error nodes automatically receive errors from all nodes.")
_info.add_header("Properties")
_info.add_bullet("Filter by Node:", "Only show errors from nodes matching this filter (leave empty for all errors)")
_info.add_header("Features")
_info.add_bullet("Auto-capture:", "Receives errors from all workflow nodes automatically")
_info.add_bullet("History:", "Keeps the last 100 errors")
_info.add_bullet("Filtering:", "Can filter errors by node name")


class ErrorNode(BaseNode):
    """
    Error node - displays error messages in the debug panel.
    Unlike debug nodes that need to be wired, error nodes automatically
    capture errors from all nodes in the workflow.
    """
    display_name = 'Error'
    icon = '⚠️'
    category = 'system'
    color = '#FF6B6B'
    border_color = '#E63946'
    text_color = '#FFFFFF'
    input_count = 0  # No input - errors come automatically
    output_count = 0  # No output - errors are displayed only
    info = str(_info)
    
    properties = [
        {
            'name': 'filter',
            'label': 'Filter by Node',
            'type': 'text',
            'placeholder': 'Leave empty for all errors'
        }
    ]
    
    def __init__(self, node_id=None, name="error"):
        super().__init__(node_id, name)
        self.configure({'filter': ''})
        self.errors = []
        self.max_errors = 100  # Keep last 100 errors
        self.is_system_node = False  # Can be set to True for the system error node
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        This won't be called since input_count = 0.
        Errors are captured via handle_error() method.
        """
        pass
    
    def handle_error(self, source_node_id: str, source_node_name: str, error_msg: str):
        """
        Handle error messages from any node in the workflow.
        This is called by the workflow engine when any node reports an error.
        """
        # Check filter
        node_filter = self.config.get('filter', '').strip()
        if node_filter and node_filter.lower() not in source_node_name.lower():
            return  # Skip this error
        
        # Create error entry
        import time
        error_entry = {
            'timestamp': time.time(),
            'source_node_id': source_node_id,
            'source_node_name': source_node_name,
            'message': error_msg,
            'type': 'error'
        }
        
        # Add to errors list
        self.errors.append(error_entry)
        
        # Trim to max size
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]
    
    def get_errors(self):
        """Get all captured errors (returns a copy so clearing doesn't affect it)."""
        return list(self.errors)
    
    def clear_errors(self):
        """Clear all captured errors."""
        self.errors.clear()

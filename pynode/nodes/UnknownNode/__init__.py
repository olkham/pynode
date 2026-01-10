"""
Unknown/Placeholder Node - represents a missing node type in the workflow.
"""

from pynode.nodes.base_node import BaseNode


class UnknownNode(BaseNode):
    """
    Placeholder node for unknown/missing node types.
    
    This node is created when loading a workflow that contains a node type
    that is not currently registered (e.g., the node was removed or renamed).
    
    The node preserves the original configuration and type information so the
    workflow can still be loaded and the user can repair/replace the node.
    """
    
    display_name = "Unknown"
    icon = "❓"
    category = "system"
    color = "#3d3d3d"
    border_color = "#ff6b6b"
    text_color = "#999"
    # input_count and output_count are handled via properties below
    hidden = True  # Don't show in palette - this is only created automatically
    
    properties = [
        {
            'name': 'original_type',
            'label': 'Original Type',
            'type': 'text',
            'default': '',
            'readonly': True
        },
        {
            'name': 'original_config',
            'label': 'Original Config',
            'type': 'json',
            'default': {},
            'readonly': True
        }
    ]
    
    info = """
    <p>This is a placeholder for a node type that could not be found.</p>
    <p>The original node type was not available when loading the workflow.</p>
    <h4>Possible reasons:</h4>
    <ul>
        <li>The node was removed or renamed</li>
        <li>A required dependency is not installed</li>
        <li>The workflow was created with a different version</li>
    </ul>
    <h4>To fix:</h4>
    <p>Delete this node and replace it with an appropriate alternative,
    or install the missing node type.</p>
    """
    
    def __init__(self, node_id=None, name="Unknown", original_type=None, 
                 original_config=None, input_count=1, output_count=1):
        super().__init__(node_id=node_id, name=name)
        self.config['original_type'] = original_type or ''
        self.config['original_config'] = original_config or {}
        # Store the original port counts so connections can still be made
        self._original_input_count = input_count
        self._original_output_count = output_count
        # Mark as disabled since it can't function
        self.enabled = False
        # Mark as unknown for frontend styling
        self._is_unknown_node = True
    
    @property
    def input_count(self):
        """Return the original input count to preserve connections."""
        return getattr(self, '_original_input_count', 1)
    
    @property
    def output_count(self):
        """Return the original output count to preserve connections."""
        return getattr(self, '_original_output_count', 1)
    
    def process(self, msg):
        """Unknown nodes don't process messages - they're just placeholders."""
        # Don't forward messages since we don't know what this node should do
        return None
    
    def on_start(self):
        """No-op for unknown nodes."""
        pass
    
    def on_stop(self):
        """No-op for unknown nodes."""
        pass

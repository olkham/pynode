"""
Template for creating custom nodes.
This demonstrates how third-party developers can create their own nodes.
"""

from typing import Any, Dict
from base_node import BaseNode


class TemplateNode(BaseNode):
    """
    Template node - example of a custom third-party node.
    Copy this file and modify to create your own nodes.
    """
    # Visual properties
    display_name = 'Template'
    icon = '📄'
    category = 'custom'  # Categories: input, output, function, logic, custom
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    # Property schema for the properties panel
    # This defines what fields appear in the UI when the node is selected
    properties = [
        {
            'name': 'template',
            'label': 'Template',
            'type': 'textarea'  # Types: text, textarea, select, button
        },
        {
            'name': 'format',
            'label': 'Output Format',
            'type': 'select',
            'options': [
                {'value': 'plain', 'label': 'Plain Text'},
                {'value': 'json', 'label': 'JSON'},
                {'value': 'html', 'label': 'HTML'}
            ]
        }
    ]
    
    def __init__(self, node_id=None, name="template"):
        super().__init__(node_id, name)
        self.configure({
            'template': 'Hello {{payload}}',
            'format': 'plain'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming messages.
        This method is called when a message arrives at the node.
        """
        template = self.config.get('template', '')
        format_type = self.config.get('format', 'plain')
        
        # Simple template replacement (in production, use a proper template engine)
        output = template.replace('{{payload}}', str(msg.get('payload', '')))
        output = output.replace('{{topic}}', str(msg.get('topic', '')))
        
        # Create new message with processed payload
        new_msg = self.create_message(
            payload=output,
            topic=msg.get('topic', '')
        )
        
        # Send to connected nodes
        self.send(new_msg)

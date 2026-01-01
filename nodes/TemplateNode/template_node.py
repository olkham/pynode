"""
Template for creating custom nodes.
This demonstrates how third-party developers can create their own nodes.
"""

from typing import Any, Dict
from nodes.base_node import BaseNode, Info

# Build info content
_info = Info()
_info.add_text("Template node for creating custom third-party nodes.")
_info.add_text("Copy this file and modify to create your own nodes.")
_info.add_header("Inputs")
_info.add_bullet("Input 0:", "Any message to process through the template")
_info.add_header("Outputs")
_info.add_bullet("Output 0:", "Message with payload replaced by template output")
_info.add_header("Properties")
_info.add_bullet("Template:", "Text template with {{payload}} and {{topic}} placeholders")
_info.add_bullet("Output Format:", "Format type: plain, json, or html")
_info.add_header("Template Variables")
_info.add_bullet("{{payload}}:", "Replaced with the message payload")
_info.add_bullet("{{topic}}:", "Replaced with the message topic")


class TemplateNode(BaseNode):
    """
    Template node - example of a custom third-party node.
    Copy this file and modify to create your own nodes.
    """
    # Visual properties
    display_name = 'Template'
    icon = '📄'
    category = 'system'  # Categories: input, output, function, logic, custom
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    info = str(_info)
    
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
        
        # Preserve original message properties (like frame_count) and update payload
        # Note: send() handles deep copying, so we modify msg directly
        msg['payload'] = output
        
        # Send to connected nodes
        self.send(msg)

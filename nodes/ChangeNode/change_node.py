"""
Change node - modifies message properties.
Similar to Node-RED's change node.
"""

from typing import Any, Dict
from nodes.base_node import BaseNode


class ChangeNode(BaseNode):
    """
    Change node - modifies message properties.
    Similar to Node-RED's change node.
    """
    display_name = 'Change'
    icon = '✎'
    category = 'function'
    color = '#E6E0F8'
    border_color = '#9F93C6'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'rules',
            'label': 'Rules',
            'type': 'text',
            'help': 'JSON array of change rules'
        }
    ]
    
    def __init__(self, node_id=None, name="change"):
        super().__init__(node_id, name)
        self.configure({
            'rules': [
                # Example: {'t': 'set', 'p': 'payload', 'to': 'value', 'tot': 'str'}
            ]
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Apply change rules to the message.
        """
        rules = self.config.get('rules', [])
        
        for rule in rules:
            rule_type = rule.get('t')  # set, change, delete, move
            property_path = rule.get('p', 'payload')
            
            if rule_type == 'set':
                value = rule.get('to')
                value_type = rule.get('tot', 'str')
                
                if value_type == 'num':
                    value = float(value)
                elif value_type == 'bool':
                    value = bool(value)
                elif value_type == 'json':
                    import json
                    value = json.loads(value) if isinstance(value, str) else value
                
                msg[property_path] = value
                
            elif rule_type == 'delete':
                if property_path in msg:
                    del msg[property_path]
                    
            elif rule_type == 'move':
                to_path = rule.get('to')
                if property_path in msg:
                    msg[to_path] = msg[property_path]
                    del msg[property_path]
        
        self.send(msg)

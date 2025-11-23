"""
Switch node - routes messages based on rules.
Similar to Node-RED's switch node.
"""

from typing import Any, Dict
from base_node import BaseNode


class SwitchNode(BaseNode):
    """
    Switch node - routes messages based on rules.
    Similar to Node-RED's switch node.
    """
    display_name = 'Switch'
    icon = '⎇'
    category = 'logic'
    color = '#E9967A'
    border_color = '#CA7C5F'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'property',
            'label': 'Property',
            'type': 'text'
        },
        {
            'name': 'rules',
            'label': 'Rules',
            'type': 'text',
            'help': 'JSON array of routing rules'
        }
    ]
    
    def __init__(self, node_id=None, name="switch"):
        super().__init__(node_id, name)
        self.configure({
            'property': 'payload',
            'rules': [
                # Example: {'t': 'eq', 'v': '10', 'vt': 'num'}
            ]
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Route message based on rules.
        """
        property_path = self.config.get('property', 'payload')
        value = msg.get(property_path)
        rules = self.config.get('rules', [])
        
        for idx, rule in enumerate(rules):
            rule_type = rule.get('t')  # eq, neq, lt, lte, gt, gte, btwn, cont, regex
            rule_value = rule.get('v')
            
            matched = False
            
            if rule_type == 'eq':
                matched = value == rule_value
            elif rule_type == 'neq':
                matched = value != rule_value
            elif rule_type == 'lt':
                matched = value < rule_value
            elif rule_type == 'lte':
                matched = value <= rule_value
            elif rule_type == 'gt':
                matched = value > rule_value
            elif rule_type == 'gte':
                matched = value >= rule_value
            elif rule_type == 'cont':
                matched = rule_value in str(value)
            elif rule_type == 'true':
                matched = bool(value)
            elif rule_type == 'false':
                matched = not bool(value)
            elif rule_type == 'else':
                matched = True
            
            if matched:
                self.send(msg, idx)
                break  # Stop after first match (unless configured otherwise)

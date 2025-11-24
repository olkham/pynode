"""
Switch node - routes messages based on rules.
Similar to Node-RED's switch node.
Supports dynamic rules with multiple outputs.
"""

import re
from typing import Any, Dict, List
from base_node import BaseNode


class SwitchNode(BaseNode):
    """
    Switch node - routes messages based on rules.
    Each rule creates a separate output port.
    Messages are routed to the first matching rule's output.
    """
    display_name = 'Switch'
    icon = '⎇'
    category = 'logic'
    color = '#E9967A'
    border_color = '#CA7C5F'
    text_color = '#000000'
    input_count = 1
    output_count = 1  # Will be dynamically updated based on rules
    
    properties = [
        {
            'name': 'property',
            'label': 'Property',
            'type': 'text',
            'help': 'The message property to evaluate (e.g., payload, topic)'
        },
        {
            'name': 'rules',
            'label': 'Rules',
            'type': 'rules',  # Custom type for rules editor
            'help': 'Define routing rules - each rule creates an output port'
        },
        {
            'name': 'checkall',
            'label': 'Check all rules',
            'type': 'checkbox',
            'default': False,
            'help': 'If checked, checks all rules and sends to all matching outputs. If unchecked, stops at first match.'
        }
    ]
    
    def __init__(self, node_id=None, name="switch"):
        super().__init__(node_id, name)
        self.configure({
            'property': 'payload',
            'checkall': False,
            'rules': [
                {'operator': 'eq', 'value': '', 'valueType': 'str'}
            ]
        })
        self._update_output_count()
    
    def configure(self, config: Dict[str, Any]):
        """Override configure to update output count when rules change."""
        super().configure(config)
        self._update_output_count()
    
    def _update_output_count(self):
        """Update the output count based on the number of rules."""
        rules = self.config.get('rules', [])
        self.output_count = max(1, len(rules))
    
    def _get_nested_value(self, msg: Dict[str, Any], property_path: str) -> Any:
        """
        Get a nested property from message using dot notation.
        e.g., 'payload.temperature' or just 'payload'
        """
        parts = property_path.split('.')
        value = msg
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value
    
    def _convert_value(self, value_str: str, value_type: str) -> Any:
        """
        Convert string value to the appropriate type.
        """
        if value_type == 'num':
            try:
                return float(value_str) if '.' in value_str else int(value_str)
            except (ValueError, TypeError):
                return 0
        elif value_type == 'bool':
            return str(value_str).lower() in ('true', '1', 'yes', 'on')
        elif value_type == 'json':
            try:
                import json
                return json.loads(value_str)
            except:
                return value_str
        else:  # 'str' or default
            return str(value_str)
    
    def _evaluate_rule(self, msg_value: Any, rule: Dict[str, Any]) -> bool:
        """
        Evaluate a single rule against a message value.
        
        Supported operators:
        - eq: equals (==)
        - neq: not equals (!=)
        - lt: less than (<)
        - lte: less than or equal (<=)
        - gt: greater than (>)
        - gte: greater than or equal (>=)
        - between: value is between two numbers
        - contains: string contains substring
        - matches: regex match
        - true: value is truthy
        - false: value is falsy
        - null: value is None
        - nnull: value is not None
        - empty: value is empty (empty string, list, dict, etc.)
        - nempty: value is not empty
        - haskey: dict has key
        - else: always matches (catch-all)
        """
        operator = rule.get('operator', 'eq')
        rule_value = rule.get('value', '')
        value_type = rule.get('valueType', 'str')
        
        try:
            # Type-specific comparisons
            if operator == 'eq':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value == compare_value
            
            elif operator == 'neq':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value != compare_value
            
            elif operator == 'lt':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value < compare_value
            
            elif operator == 'lte':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value <= compare_value
            
            elif operator == 'gt':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value > compare_value
            
            elif operator == 'gte':
                compare_value = self._convert_value(rule_value, value_type)
                return msg_value >= compare_value
            
            elif operator == 'between':
                # Expects rule_value to be "min,max"
                parts = str(rule_value).split(',')
                if len(parts) == 2:
                    min_val = self._convert_value(parts[0].strip(), value_type)
                    max_val = self._convert_value(parts[1].strip(), value_type)
                    return min_val <= msg_value <= max_val
                return False
            
            elif operator == 'contains':
                return str(rule_value) in str(msg_value)
            
            elif operator == 'matches':
                # Regex match
                pattern = str(rule_value)
                return bool(re.search(pattern, str(msg_value)))
            
            elif operator == 'true':
                return bool(msg_value)
            
            elif operator == 'false':
                return not bool(msg_value)
            
            elif operator == 'null':
                return msg_value is None
            
            elif operator == 'nnull':
                return msg_value is not None
            
            elif operator == 'empty':
                if msg_value is None:
                    return True
                if isinstance(msg_value, (str, list, dict, tuple)):
                    return len(msg_value) == 0
                return False
            
            elif operator == 'nempty':
                if msg_value is None:
                    return False
                if isinstance(msg_value, (str, list, dict, tuple)):
                    return len(msg_value) > 0
                return True
            
            elif operator == 'haskey':
                if isinstance(msg_value, dict):
                    return str(rule_value) in msg_value
                return False
            
            elif operator == 'else':
                # Catch-all rule - always matches
                return True
            
            else:
                return False
                
        except (TypeError, ValueError, AttributeError):
            return False
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Route message based on rules.
        Each rule is checked in order, and messages are sent to matching output(s).
        """
        property_path = self.config.get('property', 'payload')
        check_all = self.config.get('checkall', False)
        rules = self.config.get('rules', [])
        
        if not rules:
            # No rules defined, send to output 0
            self.send(msg, 0)
            return
        
        # Get the value to evaluate
        msg_value = self._get_nested_value(msg, property_path)
        
        # Check each rule
        matched_any = False
        for idx, rule in enumerate(rules):
            if self._evaluate_rule(msg_value, rule):
                self.send(msg, idx)
                matched_any = True
                
                # If not checking all rules, stop at first match
                if not check_all:
                    break
        
        # If no rules matched and we have an 'else' rule, it should have matched
        # Otherwise, message is not sent anywhere (filtered out)

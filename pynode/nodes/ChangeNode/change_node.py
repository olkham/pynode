"""
Change node - modifies message properties.
Similar to Node-RED's change node.
"""

import json
import re
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Modifies message properties using configurable rules. Similar to Node-RED's change node.")
_info.add_header("Input")
_info.add_bullets(
    ("msg:", "Any message to be modified according to the configured rules."),
)
_info.add_header("Output")
_info.add_bullets(
    ("msg:", "The modified message after all rules have been applied."),
)
_info.add_header("Operations")
_info.add_bullets(
    ("Set:", "Set a property to a value or copy from another property."),
    ("Change:", "Search and replace text within a property."),
    ("Delete:", "Remove a property from the message."),
    ("Move:", "Move a property to a different location."),
)


class ChangeNode(BaseNode):
    """
    Change node - modifies message properties.
    Similar to Node-RED's change node.
    
    Supports operations:
    - set: Set a property to a value or another property's value
    - change: Search and replace within a property
    - delete: Remove a property
    - move: Move a property to another location
    """
    info = str(_info)
    display_name = 'Change'
    icon = '✎'
    category = 'function'
    color = '#E6E0F8'
    border_color = '#9F93C6'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    # Custom UI component for rule editing
    ui_component = 'change-rules-editor'
    ui_component_config = {
        'operations': ['set', 'change', 'move', 'delete'],
        'value_types': [
            {'value': 'str', 'label': 'String'},
            {'value': 'num', 'label': 'Number'},
            {'value': 'bool', 'label': 'Boolean'},
            {'value': 'json', 'label': 'JSON'},
            {'value': 'msg', 'label': 'msg.'},
            {'value': 'flow', 'label': 'flow.'},
            {'value': 'global', 'label': 'global.'}
        ]
    }
    
    DEFAULT_CONFIG = {
        'rules': []
    }
    
    properties = [
        {
            'name': 'rules',
            'label': 'Rules',
            'type': 'changeRules',
            'default': [],
            'help': 'Define rules to modify message properties'
        }
    ]
    
    def __init__(self, node_id=None, name="change"):
        super().__init__(node_id, name)
    
    def _set_nested_value(self, obj: Dict, path: str, value: Any) -> bool:
        """
        Set a value at a nested path like 'payload.image.width'
        
        Args:
            obj: The object to set the value in
            path: Dot-separated path string
            value: The value to set
            
        Returns:
            True if successful, False otherwise
        """
        # Handle msg. prefix
        if path.startswith('msg.'):
            path = path[4:]
        
        parts = path.split('.')
        current = obj
        
        # Navigate to parent of target
        for part in parts[:-1]:
            # Handle array indexing
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                if key not in current:
                    current[key] = []
                current = current[key]
                index = int(index)
                while len(current) <= index:
                    current.append({})
                current = current[index]
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]
        
        # Set the final value
        final_key = parts[-1]
        match = re.match(r'(\w+)\[(\d+)\]', final_key)
        if match:
            key, index = match.groups()
            if key not in current:
                current[key] = []
            while len(current[key]) <= int(index):
                current[key].append(None)
            current[key][int(index)] = value
        else:
            current[final_key] = value
        
        return True
    
    def _delete_nested_value(self, obj: Dict, path: str) -> bool:
        """
        Delete a value at a nested path
        
        Args:
            obj: The object to delete from
            path: Dot-separated path string
            
        Returns:
            True if deleted, False otherwise
        """
        # Handle msg. prefix
        if path.startswith('msg.'):
            path = path[4:]
        
        parts = path.split('.')
        current = obj
        
        # Navigate to parent of target
        for part in parts[:-1]:
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                if isinstance(current, dict) and key in current:
                    current = current[key]
                    if isinstance(current, (list, tuple)) and int(index) < len(current):
                        current = current[int(index)]
                    else:
                        return False
                else:
                    return False
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False
        
        # Delete the final key
        final_key = parts[-1]
        match = re.match(r'(\w+)\[(\d+)\]', final_key)
        if match:
            key, index = match.groups()
            if isinstance(current, dict) and key in current:
                if isinstance(current[key], list) and int(index) < len(current[key]):
                    del current[key][int(index)]
                    return True
        elif isinstance(current, dict) and final_key in current:
            del current[final_key]
            return True
        
        return False
    
    def _resolve_value(self, msg: Dict, value: Any, value_type: str) -> Any:
        """
        Resolve a value based on its type.
        
        Args:
            msg: The message object
            value: The value or path
            value_type: Type of the value ('str', 'num', 'bool', 'json', 'msg', etc.)
            
        Returns:
            The resolved value
        """
        if value_type == 'msg':
            # Get value from message path
            return self._get_nested_value(msg, value)
        elif value_type == 'num':
            try:
                return float(value) if '.' in str(value) else int(value)
            except (ValueError, TypeError):
                return 0
        elif value_type == 'bool':
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes', 'on')
        elif value_type == 'json':
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        elif value_type == 'str':
            return str(value) if value is not None else ''
        else:
            # Default: return as-is
            return value
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Apply change rules to the message.
        """
        rules = self.config.get('rules', [])
        
        # Handle rules as JSON string (from UI)
        if isinstance(rules, str):
            try:
                rules = json.loads(rules)
            except json.JSONDecodeError:
                rules = []
        
        for rule in rules:
            if not isinstance(rule, dict):
                continue
                
            rule_type = rule.get('type', rule.get('t', 'set'))
            property_path = rule.get('path', rule.get('p', rule.get('property', f'msg.{MessageKeys.PAYLOAD}')))
            
            try:
                if rule_type == 'set':
                    # Set property to a value
                    value = rule.get('value', rule.get('to', ''))
                    value_type = rule.get('valueType', rule.get('tot', 'str'))
                    
                    # Handle path value type (read from another msg property)
                    if value_type == 'path':
                        resolved_value = self._get_nested_value(msg, 'msg.' + str(value) if not str(value).startswith('msg.') else value)
                    elif value_type == 'date':
                        import time
                        resolved_value = int(time.time() * 1000)
                    elif value_type == 'env':
                        import os
                        resolved_value = os.environ.get(str(value), '')
                    else:
                        resolved_value = self._resolve_value(msg, value, value_type)
                    
                    self._set_nested_value(msg, property_path, resolved_value)
                    
                elif rule_type == 'change':
                    # Search and replace within a property
                    search = rule.get('search', rule.get('from', ''))
                    search_type = rule.get('searchType', rule.get('fromt', 'str'))
                    replace = rule.get('replace', rule.get('to', ''))
                    replace_type = rule.get('replaceType', rule.get('tot', 'str'))
                    
                    current_value = self._get_nested_value(msg, property_path)
                    
                    # Resolve replace value
                    if replace_type == 'path':
                        replace_value = self._get_nested_value(msg, 'msg.' + str(replace) if not str(replace).startswith('msg.') else replace)
                    else:
                        replace_value = str(replace)
                    
                    if current_value is not None:
                        if isinstance(current_value, str):
                            if search_type == 'regex':
                                try:
                                    new_value = re.sub(search, str(replace_value) if replace_value else '', current_value)
                                    self._set_nested_value(msg, property_path, new_value)
                                except re.error as e:
                                    self.report_error(f"Invalid regex pattern: {search}")
                            else:
                                new_value = current_value.replace(str(search), str(replace_value) if replace_value else '')
                                self._set_nested_value(msg, property_path, new_value)
                    
                elif rule_type == 'delete':
                    # Delete a property
                    self._delete_nested_value(msg, property_path)
                    
                elif rule_type == 'move':
                    # Move property to another location
                    to_path = rule.get('toPath', rule.get('to', rule.get('toProperty', '')))
                    
                    if to_path:
                        current_value = self._get_nested_value(msg, property_path)
                        if current_value is not None:
                            self._set_nested_value(msg, to_path, current_value)
                            self._delete_nested_value(msg, property_path)
                            
            except Exception as e:
                self.report_error(f"Error applying rule {rule_type} on {property_path}: {str(e)}")
        
        self.send(msg)

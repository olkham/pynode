"""
Change node - modifies message properties.
Similar to Node-RED's change node.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
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
_info.add_header("Lists")
_info.add_text(
    "Tick 'is list' on a rule when the property holds a list of objects, and "
    "give the key to work on. The rule then applies to that key in every item, "
    "however many there are - for example relabelling each detection:"
)
_info.add_code("in msg.payload.detections - is list, key class_name - search 2, replace drone").end()
_info.add_text(
    "Search-and-replace works on substrings of text values. A value that is "
    "not text (a number, a boolean) is replaced only when the search matches "
    "the whole value, and the replacement keeps the type you selected."
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
    
    DEFAULT_CONFIG = {
        'rules': []
    }
    
    # Editor UI for this node's custom property type (see BaseNode.ui_assets).
    ui_assets = {'js': ['ui/change-rules.js']}

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
    
    def _rule_targets(self, msg: Dict, rule: Dict, path: str) -> List[Tuple[Optional[Dict], str]]:
        """Work out the places a rule applies to.

        Normally that is one place: the property path itself. With ``isList``
        set, the path must hold a list, and the rule applies to ``key`` inside
        every object in it - the way to rewrite a field on all detections
        without knowing how many there are.

        Args:
            msg: The message being modified.
            rule: The rule definition.
            path: The rule's property path.

        Returns:
            ``(container, key)`` pairs. ``container`` is None for a plain
            property path, in which case ``key`` is that path.
        """
        if not rule.get('isList', rule.get('is_list', False)):
            return [(None, path)]

        key = str(rule.get('key', rule.get('itemKey', '')) or '').strip()
        if not key:
            self.report_error(f"List rule on {path} needs an item key")
            return []

        items = self._get_nested_value(msg, path)
        if not isinstance(items, (list, tuple)):
            self.report_error(f"List rule on {path}: not a list")
            return []

        return [(item, key) for item in items if isinstance(item, dict)]

    def _target_get(self, msg: Dict, target: Tuple[Optional[Dict], str]) -> Any:
        """Read a target - a message path, or a key inside a list item."""
        container, key = target
        if container is None:
            return self._get_nested_value(msg, key)
        return container.get(key)

    def _target_set(self, msg: Dict, target: Tuple[Optional[Dict], str], value: Any) -> None:
        """Write a target."""
        container, key = target
        if container is None:
            self._set_nested_value(msg, key, value)
        else:
            container[key] = value

    def _target_delete(self, msg: Dict, target: Tuple[Optional[Dict], str]) -> bool:
        """Remove a target, reporting whether anything was there."""
        container, key = target
        if container is None:
            return self._delete_nested_value(msg, key)
        if key in container:
            del container[key]
            return True
        return False

    def _apply_change(self, msg: Dict, target: Tuple[Optional[Dict], str],
                      search: Any, search_type: str,
                      replacement_text: str, replacement_value: Any) -> None:
        """Search and replace inside one target.

        Text is replaced by substring (or regex). Anything else - a number, a
        boolean - has no substring to work on, so it is replaced only when the
        search matches the whole value, and it takes the typed replacement.
        """
        current = self._target_get(msg, target)
        if current is None:
            return

        if isinstance(current, str):
            if search_type == 'regex':
                try:
                    self._target_set(msg, target, re.sub(str(search), replacement_text, current))
                except re.error:
                    self.report_error(f"Invalid regex pattern: {search}")
            else:
                self._target_set(msg, target, current.replace(str(search), replacement_text))
        elif not isinstance(current, (dict, list, tuple)) and str(current) == str(search):
            self._target_set(msg, target, replacement_value)

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
                # One target for a plain path; one per list item in list mode.
                targets = self._rule_targets(msg, rule, property_path)
                if not targets:
                    continue

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
                    
                    for target in targets:
                        self._target_set(msg, target, resolved_value)
                    
                elif rule_type == 'change':
                    # Search and replace within a property
                    search = rule.get('search', rule.get('from', ''))
                    search_type = rule.get('searchType', rule.get('fromt', 'str'))
                    replace = rule.get('replace', rule.get('to', ''))
                    replace_type = rule.get('replaceType', rule.get('tot', 'str'))
                    
                    # Resolve the replacement twice over: the text form drives
                    # substring and regex replacement, the typed form replaces a
                    # whole non-text value (see _apply_change).
                    if replace_type == 'path':
                        replacement_value = self._get_nested_value(msg, 'msg.' + str(replace) if not str(replace).startswith('msg.') else replace)
                    else:
                        replacement_value = self._resolve_value(msg, replace, replace_type)
                    replacement_text = str(replacement_value) if replacement_value is not None else ''
                    
                    for target in targets:
                        self._apply_change(msg, target, search, search_type,
                                           replacement_text, replacement_value)
                    
                elif rule_type == 'delete':
                    # Delete a property
                    for target in targets:
                        self._target_delete(msg, target)
                    
                elif rule_type == 'move':
                    # Move property to another location. In list mode the
                    # destination is a key inside the same item.
                    to_path = rule.get('toPath', rule.get('to', rule.get('toProperty', '')))
                    
                    if to_path:
                        for target in targets:
                            container, _ = target
                            current_value = self._target_get(msg, target)
                            if current_value is not None:
                                self._target_set(msg, (container, to_path), current_value)
                                self._target_delete(msg, target)
                            
            except Exception as e:
                self.report_error(f"Error applying rule {rule_type} on {property_path}: {str(e)}")
        
        self.send(msg)

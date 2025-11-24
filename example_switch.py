"""
Example workflow demonstrating the enhanced Switch node.
Shows how to route messages to different outputs based on rules.
"""

from workflow_engine import WorkflowEngine
from nodes import InjectNode, SwitchNode, DebugNode

def create_switch_workflow():
    """Create an example workflow with the enhanced switch node."""
    
    # Initialize engine
    engine = WorkflowEngine()
    
    # Register node types
    engine.register_node_type(InjectNode)
    engine.register_node_type(SwitchNode)
    engine.register_node_type(DebugNode)
    
    print("Creating switch example workflow...")
    
    # Create inject nodes with different values
    inject_low = engine.create_node(
        'InjectNode', 
        name='low_value',
        config={'payload': 5, 'payloadType': 'num', 'topic': 'temperature'}
    )
    
    inject_medium = engine.create_node(
        'InjectNode', 
        name='medium_value',
        config={'payload': 25, 'payloadType': 'num', 'topic': 'temperature'}
    )
    
    inject_high = engine.create_node(
        'InjectNode', 
        name='high_value',
        config={'payload': 45, 'payloadType': 'num', 'topic': 'temperature'}
    )
    
    # Create a switch node with multiple rules
    # Rule 1: payload < 10 -> Output 1 (Cold)
    # Rule 2: payload < 30 -> Output 2 (Warm)
    # Rule 3: payload >= 30 -> Output 3 (Hot)
    switch = engine.create_node(
        'SwitchNode',
        name='temperature_router',
        config={
            'property': 'payload',
            'checkall': False,
            'rules': [
                {'operator': 'lt', 'value': '10', 'valueType': 'num'},   # Output 1: Cold
                {'operator': 'lt', 'value': '30', 'valueType': 'num'},   # Output 2: Warm
                {'operator': 'gte', 'value': '30', 'valueType': 'num'},  # Output 3: Hot
            ]
        }
    )
    
    # Create debug nodes for each output
    debug_cold = engine.create_node(
        'DebugNode',
        name='cold_alert'
    )
    
    debug_warm = engine.create_node(
        'DebugNode',
        name='warm_normal'
    )
    
    debug_hot = engine.create_node(
        'DebugNode',
        name='hot_warning'
    )
    
    # Connect the nodes:
    # All inject nodes -> switch
    # switch output 0 -> debug_cold
    # switch output 1 -> debug_warm
    # switch output 2 -> debug_hot
    
    engine.connect_nodes(inject_low.id, switch.id, output_index=0, input_index=0)
    engine.connect_nodes(inject_medium.id, switch.id, output_index=0, input_index=0)
    engine.connect_nodes(inject_high.id, switch.id, output_index=0, input_index=0)
    
    engine.connect_nodes(switch.id, debug_cold.id, output_index=0, input_index=0)
    engine.connect_nodes(switch.id, debug_warm.id, output_index=1, input_index=0)
    engine.connect_nodes(switch.id, debug_hot.id, output_index=2, input_index=0)
    
    print(f"\nWorkflow created with {len(engine.nodes)} nodes")
    
    # Start the workflow
    engine.start()
    print("\nWorkflow started!")
    
    # Trigger each inject node
    print("\n=== Testing Low Value (5) ===")
    engine.trigger_inject_node(inject_low.id)
    
    import time
    time.sleep(0.2)
    
    print("\n=== Testing Medium Value (25) ===")
    engine.trigger_inject_node(inject_medium.id)
    
    time.sleep(0.2)
    
    print("\n=== Testing High Value (45) ===")
    engine.trigger_inject_node(inject_high.id)
    
    time.sleep(0.2)
    
    # Show debug messages from each output
    print("\n=== Cold Alert (< 10) ===")
    messages_cold = engine.get_debug_messages(debug_cold.id)
    for msg in messages_cold:
        print(f"[{msg['timestamp']}] {msg['output']}")
    
    print("\n=== Warm Normal (10-30) ===")
    messages_warm = engine.get_debug_messages(debug_warm.id)
    for msg in messages_warm:
        print(f"[{msg['timestamp']}] {msg['output']}")
    
    print("\n=== Hot Warning (>= 30) ===")
    messages_hot = engine.get_debug_messages(debug_hot.id)
    for msg in messages_hot:
        print(f"[{msg['timestamp']}] {msg['output']}")
    
    # Export the workflow
    workflow_data = engine.export_workflow()
    print("\n=== Workflow Export ===")
    import json
    print(json.dumps(workflow_data, indent=2))
    
    # Stop the workflow
    engine.stop()
    print("\nWorkflow stopped!")
    
    return engine


def create_advanced_switch_example():
    """Create an advanced example showing different operator types."""
    
    engine = WorkflowEngine()
    
    # Register node types
    engine.register_node_type(InjectNode)
    engine.register_node_type(SwitchNode)
    engine.register_node_type(DebugNode)
    
    print("\n\n=== Advanced Switch Example ===")
    print("Demonstrating various operators...\n")
    
    # Create inject nodes with different types of data
    inject_string = engine.create_node(
        'InjectNode', 
        name='string_input',
        config={'payload': 'hello world', 'payloadType': 'str'}
    )
    
    inject_dict = engine.create_node(
        'InjectNode', 
        name='dict_input',
        config={'payload': '{"status": "active", "count": 42}', 'payloadType': 'json'}
    )
    
    # Switch node with various operators
    switch = engine.create_node(
        'SwitchNode',
        name='advanced_router',
        config={
            'property': 'payload',
            'checkall': False,
            'rules': [
                {'operator': 'contains', 'value': 'hello', 'valueType': 'str'},  # Check if contains 'hello'
                {'operator': 'haskey', 'value': 'status', 'valueType': 'str'},    # Check if dict has 'status' key
                {'operator': 'empty', 'value': '', 'valueType': 'str'},           # Check if empty
                {'operator': 'else', 'value': '', 'valueType': 'str'},            # Catch-all
            ]
        }
    )
    
    # Create debug nodes
    debug_contains = engine.create_node('DebugNode', name='contains_hello')
    debug_haskey = engine.create_node('DebugNode', name='has_status_key')
    debug_empty = engine.create_node('DebugNode', name='is_empty')
    debug_else = engine.create_node('DebugNode', name='otherwise')
    
    # Connect nodes
    engine.connect_nodes(inject_string.id, switch.id)
    engine.connect_nodes(inject_dict.id, switch.id)
    
    engine.connect_nodes(switch.id, debug_contains.id, output_index=0)
    engine.connect_nodes(switch.id, debug_haskey.id, output_index=1)
    engine.connect_nodes(switch.id, debug_empty.id, output_index=2)
    engine.connect_nodes(switch.id, debug_else.id, output_index=3)
    
    # Start and test
    engine.start()
    
    print("Testing string input...")
    engine.trigger_inject_node(inject_string.id)
    
    import time
    time.sleep(0.2)
    
    print("Testing dict input...")
    engine.trigger_inject_node(inject_dict.id)
    
    time.sleep(0.2)
    
    # Show results
    print("\n=== Contains 'hello' ===")
    for msg in engine.get_debug_messages(debug_contains.id):
        print(f"  {msg['output']}")
    
    print("\n=== Has 'status' key ===")
    for msg in engine.get_debug_messages(debug_haskey.id):
        print(f"  {msg['output']}")
    
    engine.stop()
    return engine


if __name__ == '__main__':
    # Run basic switch example
    create_switch_workflow()
    
    # Run advanced switch example
    create_advanced_switch_example()

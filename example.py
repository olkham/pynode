"""
Example workflow demonstrating the PyNode system.
Creates a simple workflow programmatically.
"""

from workflow_engine import WorkflowEngine
from nodes import InjectNode, FunctionNode, DebugNode, ChangeNode

def create_example_workflow():
    """Create an example workflow with several connected nodes."""
    
    # Initialize engine
    engine = WorkflowEngine()
    
    # Register node types
    engine.register_node_type(InjectNode)
    engine.register_node_type(FunctionNode)
    engine.register_node_type(DebugNode)
    engine.register_node_type(ChangeNode)
    
    print("Creating example workflow...")
    
    # Create an inject node that sends a number
    inject1 = engine.create_node(
        'InjectNode', 
        name='inject_number',
        config={'payload': 5, 'payloadType': 'num', 'topic': 'math'}
    )
    
    # Create a function node that multiplies by 2
    multiply = engine.create_node(
        'FunctionNode',
        name='multiply_by_2',
        config={'func': 'msg["payload"] = msg["payload"] * 2\nreturn msg'}
    )
    
    # Create a change node that adds a property
    change = engine.create_node(
        'ChangeNode',
        name='add_timestamp',
        config={
            'rules': [
                {'t': 'set', 'p': 'timestamp', 'to': 'time.time()', 'tot': 'str'}
            ]
        }
    )
    
    # Create debug nodes
    debug1 = engine.create_node(
        'DebugNode',
        name='debug_original'
    )
    
    debug2 = engine.create_node(
        'DebugNode',
        name='debug_multiplied'
    )
    
    # Connect the nodes:
    # inject1 -> debug1 (to see original value)
    # inject1 -> multiply -> change -> debug2 (to see processed value)
    
    engine.connect_nodes(inject1.id, debug1.id)
    engine.connect_nodes(inject1.id, multiply.id)
    engine.connect_nodes(multiply.id, change.id)
    engine.connect_nodes(change.id, debug2.id)
    
    print(f"\nWorkflow created with {len(engine.nodes)} nodes")
    print(f"Connections: {len([c for conns in engine.nodes.values() for c in conns.outputs.values()])}")
    
    # Start the workflow
    engine.start()
    print("\nWorkflow started!")
    
    # Trigger the inject node
    print("\nTriggering inject node...")
    engine.trigger_inject_node(inject1.id)
    
    # Wait a moment for processing
    import time
    time.sleep(0.5)
    
    # Show debug messages
    print("\n=== Debug Output (Original) ===")
    messages1 = engine.get_debug_messages(debug1.id)
    for msg in messages1:
        print(f"[{msg['timestamp']}] {msg['output']}")
    
    print("\n=== Debug Output (Processed) ===")
    messages2 = engine.get_debug_messages(debug2.id)
    for msg in messages2:
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


if __name__ == '__main__':
    create_example_workflow()

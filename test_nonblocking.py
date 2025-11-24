"""
Test script to demonstrate non-blocking message flow.
Creates a workflow with fast inject and slow delay to show parallel processing.
"""

import time
from workflow_engine import WorkflowEngine
from nodes import InjectNode, DelayNode, DebugNode

def test_nonblocking_flow():
    """
    Test that demonstrates non-blocking message flow.
    
    Flow:
    Inject (0.1s interval) -> Delay (1s) -> Debug
    
    Expected behavior:
    - Messages are injected every 0.1 seconds
    - Each message is delayed by 1 second
    - After the initial 1 second delay, debug should receive messages every 0.1 seconds
    - This proves the system is non-blocking (delay doesn't slow down inject rate)
    """
    
    print("=" * 60)
    print("Non-Blocking Flow Test")
    print("=" * 60)
    print("\nSetup:")
    print("  Inject: Every 0.1 seconds")
    print("  Delay: 1 second")
    print("  Expected: After 1s warmup, debug receives msgs every 0.1s")
    print("\n" + "=" * 60 + "\n")
    
    # Create engine and register nodes
    engine = WorkflowEngine()
    engine.register_node_type(InjectNode)
    engine.register_node_type(DelayNode)
    engine.register_node_type(DebugNode)
    
    # Create nodes
    inject = engine.create_node(
        'InjectNode',
        name='fast_inject',
        config={
            'payload': 0,
            'payloadType': 'num',
            'topic': 'test',
            'repeat': '0.1',  # Inject every 0.1 seconds
            'once': ''
        }
    )
    
    delay = engine.create_node(
        'DelayNode',
        name='slow_delay',
        config={
            'timeout': 1.0  # 1 second delay
        }
    )
    
    debug = engine.create_node(
        'DebugNode',
        name='output'
    )
    
    # Connect: inject -> delay -> debug
    engine.connect_nodes(inject.id, delay.id)
    engine.connect_nodes(delay.id, debug.id)
    
    # Start workflow
    print("Starting workflow...")
    engine.start()
    
    # Let it run and monitor message timing
    print("\nMonitoring message flow (15 seconds)...")
    print("Time | Messages Received | Rate")
    print("-" * 50)
    
    start_time = time.time()
    last_count = 0
    
    for i in range(15):
        time.sleep(1)
        elapsed = time.time() - start_time
        messages = engine.get_debug_messages(debug.id)
        count = len(messages)
        rate = (count - last_count) if i > 0 else 0
        
        print(f"{elapsed:4.1f}s | {count:17d} | {rate}/s")
        
        last_count = count
    
    # Stop workflow
    engine.stop()
    
    # Analyze results
    messages = engine.get_debug_messages(debug.id)
    print("\n" + "=" * 60)
    print("Results:")
    print(f"  Total messages received: {len(messages)}")
    print(f"  Expected (non-blocking): ~140 messages (14s × 10 msgs/s)")
    print(f"  Expected (blocking): ~14 messages (14 msgs × 1s delay each)")
    
    if len(messages) > 100:
        print("\n✓ SUCCESS: System is non-blocking!")
        print("  Messages flowed through delay without blocking the inject rate.")
    elif len(messages) < 30:
        print("\n✗ FAILURE: System appears to be blocking")
        print("  Delay is limiting the entire flow rate.")
    else:
        print("\n⚠ PARTIAL: System may have some blocking")
    
    print("=" * 60 + "\n")
    
    # Show message timing details
    if messages:
        print("Message timing (first 10):")
        for i, msg in enumerate(messages[:10]):
            timestamp = msg.get('timestamp', 'N/A')
            payload = msg.get('output', {}).get('payload', 'N/A')
            print(f"  {i+1}. [{timestamp}] payload={payload}")
    
    return engine, len(messages)


def test_parallel_paths():
    """
    Test multiple parallel paths with different delays.
    
    Flow:
                    -> Delay(0.5s) -> Debug1
    Inject(0.1s) --|
                    -> Delay(2.0s) -> Debug2
    
    Both paths should operate independently without blocking each other.
    """
    
    print("\n\n" + "=" * 60)
    print("Parallel Paths Test")
    print("=" * 60)
    print("\nSetup:")
    print("  Inject: Every 0.1 seconds")
    print("  Path 1: 0.5s delay -> Debug1")
    print("  Path 2: 2.0s delay -> Debug2")
    print("  Expected: Both paths operate independently")
    print("\n" + "=" * 60 + "\n")
    
    engine = WorkflowEngine()
    engine.register_node_type(InjectNode)
    engine.register_node_type(DelayNode)
    engine.register_node_type(DebugNode)
    
    # Create nodes
    inject = engine.create_node(
        'InjectNode',
        name='source',
        config={
            'payload': 'msg',
            'payloadType': 'string',
            'repeat': '0.1'
        }
    )
    
    delay1 = engine.create_node('DelayNode', name='fast', config={'timeout': 0.5})
    delay2 = engine.create_node('DelayNode', name='slow', config={'timeout': 2.0})
    debug1 = engine.create_node('DebugNode', name='debug_fast')
    debug2 = engine.create_node('DebugNode', name='debug_slow')
    
    # Connect parallel paths
    engine.connect_nodes(inject.id, delay1.id, output_index=0)
    engine.connect_nodes(inject.id, delay2.id, output_index=0)
    engine.connect_nodes(delay1.id, debug1.id)
    engine.connect_nodes(delay2.id, debug2.id)
    
    print("Starting workflow...")
    engine.start()
    
    # Monitor for 10 seconds
    print("\nMonitoring (10 seconds)...")
    for i in range(10):
        time.sleep(1)
        count1 = len(engine.get_debug_messages(debug1.id))
        count2 = len(engine.get_debug_messages(debug2.id))
        print(f"{i+1}s: Fast path={count1:3d} msgs, Slow path={count2:3d} msgs")
    
    engine.stop()
    
    count1 = len(engine.get_debug_messages(debug1.id))
    count2 = len(engine.get_debug_messages(debug2.id))
    
    print("\n" + "=" * 60)
    print("Results:")
    print(f"  Fast path (0.5s): {count1} messages")
    print(f"  Slow path (2.0s): {count2} messages")
    print(f"  Ratio: {count1/count2:.1f}:1 (expected ~4:1)")
    
    if count1 > count2 * 2:
        print("\n✓ SUCCESS: Paths are independent and non-blocking!")
    else:
        print("\n✗ FAILURE: Paths appear to be interfering")
    
    print("=" * 60 + "\n")


if __name__ == '__main__':
    # Run tests
    engine1, msg_count = test_nonblocking_flow()
    
    test_parallel_paths()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\nThe non-blocking architecture uses:")
    print("  1. Message queues for each node")
    print("  2. Worker threads to process messages asynchronously")
    print("  3. Timer-based delays instead of blocking sleep")
    print("\nThis allows high-throughput message flows even with")
    print("slow processing nodes in the pipeline.")
    print("=" * 60 + "\n")

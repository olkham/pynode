"""BaseNode messaging semantics tests.

Nodes are constructed directly and exercised synchronously wherever possible:
``send()`` only queues (or drops) messages, so its behavior can be asserted by
inspecting ``_message_queue`` without ever starting worker threads. Only the
explicit worker-lifecycle test starts a real thread, and it joins it in a
try/finally before returning.
"""

import queue
import threading
import uuid

import pytest

from pynode.nodes.base_node import BaseNode, MessageKeys, sort_msg_keys


class _StubEngine:
    """Captures broadcast_error calls made via BaseNode.report_error."""

    def __init__(self):
        self.errors = []

    def broadcast_error(self, node_id, node_name, error_msg):
        self.errors.append((node_id, node_name, error_msg))


class _DirectSink(BaseNode):
    """Sink (no outputs) with on_input_direct: send() delivers synchronously."""

    input_count = 1
    output_count = 0

    def __init__(self, node_id=None, name=""):
        super().__init__(node_id=node_id, name=name)
        self.received = []

    def on_input_direct(self, msg, input_index=0):
        self.received.append((msg, input_index))


class _Recorder(BaseNode):
    """Node whose on_input records messages and signals an event."""

    input_count = 1
    output_count = 1

    def __init__(self, node_id=None, name=""):
        super().__init__(node_id=node_id, name=name)
        self.processed = []
        self.got_message = threading.Event()

    def on_input(self, msg, input_index=0):
        self.processed.append(msg)
        self.got_message.set()


def _queued_pair():
    """Source connected to a plain BaseNode target (queue delivery path)."""
    src = BaseNode(name='src')
    target = BaseNode(name='target')
    src.connect(target, 0, 0)
    return src, target


# ------------------------------------------------------------------
# drop_while_busy semantics
# ------------------------------------------------------------------

class TestDropWhileBusy:

    def test_drop_when_target_processing(self):
        src, target = _queued_pair()
        target._processing = True

        src.send(src.create_message(payload='x'))

        assert target._message_queue.empty()
        # The drop counter is incremented on the TARGET node, not the sender
        assert target.drop_count == 1
        assert src.drop_count == 0

    def test_drop_when_target_queue_nonempty(self):
        src, target = _queued_pair()
        target._message_queue.put_nowait(({'payload': 'old'}, 0))

        src.send(src.create_message(payload='new'))

        assert target._message_queue.qsize() == 1  # nothing was added
        assert target.drop_count == 1

    def test_no_drop_when_target_idle(self):
        src, target = _queued_pair()
        src.send(src.create_message(payload='x'))

        assert target._message_queue.qsize() == 1
        assert target.drop_count == 0

    def test_delivered_message_carries_sender_drop_count(self):
        src, target = _queued_pair()
        src.drop_count = 7  # messages previously dropped when sending TO src

        src.send(src.create_message(payload='x'))

        msg, input_index = target._message_queue.get_nowait()
        assert msg[MessageKeys.DROP_COUNT] == 7
        assert input_index == 0

    def test_drop_disabled_queues_even_when_busy(self):
        src, target = _queued_pair()
        target.configure({MessageKeys.DROP_MESSAGES: False})
        target._processing = True

        src.send(src.create_message(payload='x'))

        assert target._message_queue.qsize() == 1
        assert target.drop_count == 0


# ------------------------------------------------------------------
# Queue-full error path
# ------------------------------------------------------------------

def test_queue_full_reports_error_on_target():
    src, target = _queued_pair()
    target.configure({MessageKeys.DROP_MESSAGES: False})
    engine = _StubEngine()
    target.set_workflow_engine(engine)
    # Replace the queue with a tiny one and fill it
    target._message_queue = queue.Queue(maxsize=1)
    target._message_queue.put_nowait(({'payload': 'filler'}, 0))

    src.send(src.create_message(payload='overflow'))

    assert target._message_queue.qsize() == 1  # message was dropped
    assert len(engine.errors) == 1
    node_id, node_name, error_msg = engine.errors[0]
    assert node_id == target.id
    assert 'queue full' in error_msg.lower()


# ------------------------------------------------------------------
# Deep-copy isolation between recipients
# ------------------------------------------------------------------

def test_deep_copy_isolation_between_recipients():
    src = BaseNode(name='src')
    t1 = BaseNode(name='t1')
    t2 = BaseNode(name='t2')
    src.connect(t1, 0, 0)
    src.connect(t2, 0, 0)

    original = src.create_message(payload={'k': {'v': 1}})
    src.send(original)

    msg1, _ = t1._message_queue.get_nowait()
    msg2, _ = t2._message_queue.get_nowait()
    assert msg1 is not msg2
    assert msg1['payload'] == {'k': {'v': 1}}

    # Mutating one recipient's copy affects neither the sibling nor the source
    msg1['payload']['k']['v'] = 999
    msg1['payload']['extra'] = True
    assert msg2['payload'] == {'k': {'v': 1}}
    assert original['payload'] == {'k': {'v': 1}}


# ------------------------------------------------------------------
# on_input_direct sink path (synchronous delivery)
# ------------------------------------------------------------------

class TestDirectSinkPath:

    def test_synchronous_delivery_with_metadata(self):
        src = BaseNode(name='src')
        sink = _DirectSink(name='sink')
        src.connect(sink, 0, 0)

        src.send(src.create_message(payload='hello', topic='t'))

        assert len(sink.received) == 1  # delivered synchronously, no threads
        msg, input_index = sink.received[0]
        assert input_index == 0
        assert msg['payload'] == 'hello'
        assert msg['topic'] == 't'
        assert MessageKeys.TIMESTAMP_EMIT in msg
        assert MessageKeys.AGE in msg
        assert MessageKeys.QUEUE_LENGTH in msg
        assert msg[MessageKeys.AGE] >= 0
        # Nothing lands on the sink's queue in the direct path
        assert sink._message_queue.empty()

    def test_keys_sorted_underscore_first(self):
        src = BaseNode(name='src')
        sink = _DirectSink(name='sink')
        src.connect(sink, 0, 0)

        src.send(src.create_message(payload='p', topic='t', zebra=1, alpha=2))

        msg, _ = sink.received[0]
        keys = list(msg.keys())
        assert keys == sorted(keys, key=lambda k: (not k.startswith('_'), k))
        # Underscore (metadata) keys strictly precede plain keys
        underscore = [k for k in keys if k.startswith('_')]
        assert keys[:len(underscore)] == underscore

    def test_direct_sink_exception_reported_not_raised(self):
        class _Boom(_DirectSink):
            def on_input_direct(self, msg, input_index=0):
                raise RuntimeError('boom')

        src = BaseNode(name='src')
        sink = _Boom(name='boom-sink')
        engine = _StubEngine()
        sink.set_workflow_engine(engine)
        src.connect(sink, 0, 0)

        src.send(src.create_message(payload='x'))  # must not raise

        assert len(engine.errors) == 1
        assert 'boom' in engine.errors[0][2]


# ------------------------------------------------------------------
# Enabled/disabled gating
# ------------------------------------------------------------------

class TestEnabledGating:

    def test_disabled_source_sends_nothing(self):
        src, target = _queued_pair()
        sink = _DirectSink(name='sink')
        src.connect(sink, 0, 0)
        src.enabled = False

        src.send(src.create_message(payload='x'))

        assert target._message_queue.empty()
        assert sink.received == []

    def test_disabled_target_receives_nothing(self):
        src, target = _queued_pair()
        sink = _DirectSink(name='sink')
        src.connect(sink, 0, 0)
        target.enabled = False
        sink.enabled = False

        src.send(src.create_message(payload='x'))

        assert target._message_queue.empty()
        assert target.drop_count == 0  # skipped, not counted as a drop
        assert sink.received == []


# ------------------------------------------------------------------
# Worker lifecycle (the one test that uses a real thread)
# ------------------------------------------------------------------

def test_worker_start_processes_queue_and_stop_joins():
    node = _Recorder(name='worker')
    node.on_start()
    try:
        assert node._worker_thread is not None
        assert node._worker_thread.is_alive()

        node._message_queue.put_nowait(({'payload': 'job'}, 0))
        assert node.got_message.wait(timeout=2.0), 'worker never processed msg'
        assert node.processed[0]['payload'] == 'job'
    finally:
        node.on_stop()

    assert node._stop_worker_flag is True
    assert not node._worker_thread.is_alive()


def test_on_stop_without_start_is_safe():
    node = BaseNode(name='never-started')
    node.on_stop()  # must not raise
    assert node._worker_thread is None


# ------------------------------------------------------------------
# create_message
# ------------------------------------------------------------------

class TestCreateMessage:

    def test_basic_payload_and_topic(self):
        node = BaseNode()
        msg = node.create_message(payload={'a': 1}, topic='news')
        assert msg[MessageKeys.PAYLOAD] == {'a': 1}
        assert msg[MessageKeys.TOPIC] == 'news'
        assert isinstance(msg[MessageKeys.TIMESTAMP_ORIG], float)
        uuid.UUID(msg[MessageKeys.MSG_ID])  # valid uuid string

    def test_msgid_unique_per_message(self):
        node = BaseNode()
        ids = {node.create_message(payload=i)[MessageKeys.MSG_ID]
               for i in range(5)}
        assert len(ids) == 5

    def test_default_payload_none_omits_key(self):
        node = BaseNode()
        msg = node.create_message()
        assert MessageKeys.PAYLOAD not in msg
        assert MessageKeys.TOPIC not in msg  # empty topic omitted too

    def test_explicit_none_payload_is_omitted(self):
        # NOTE (product-code quirk): create_message() has a branch meant to
        # include an explicitly-passed payload=None ("if PAYLOAD in kwargs"),
        # but 'payload' is a named parameter, so it can never appear in
        # **kwargs - that branch is unreachable dead code. Actual behavior:
        # an explicit None payload is always omitted from the message.
        node = BaseNode()
        msg = node.create_message(**{MessageKeys.PAYLOAD: None})
        assert MessageKeys.PAYLOAD not in msg
        msg = node.create_message(payload=None)
        assert MessageKeys.PAYLOAD not in msg

    def test_extra_kwargs_merged(self):
        node = BaseNode()
        msg = node.create_message(payload=1, custom_field='yes')
        assert msg['custom_field'] == 'yes'


# ------------------------------------------------------------------
# _get_nested_value / _set_nested_value
# ------------------------------------------------------------------

class TestNestedValueAccess:

    @pytest.fixture
    def node(self):
        return BaseNode()

    def test_get_simple_and_dotted(self, node):
        msg = {'payload': {'data': {'value': 42}}}
        assert node._get_nested_value(msg, 'payload') == {'data': {'value': 42}}
        assert node._get_nested_value(msg, 'payload.data.value') == 42

    def test_get_array_indexing(self, node):
        msg = {'items': [{'name': 'first'}, {'name': 'second'}]}
        assert node._get_nested_value(msg, 'items[0].name') == 'first'
        assert node._get_nested_value(msg, 'items[1].name') == 'second'
        assert node._get_nested_value(msg, 'items[2].name') is None  # OOB

    def test_get_msg_prefix_stripped(self, node):
        msg = {'payload': 'hi'}
        assert node._get_nested_value(msg, 'msg.payload') == 'hi'

    def test_get_missing_path_returns_none(self, node):
        msg = {'payload': {'a': 1}}
        assert node._get_nested_value(msg, 'payload.b') is None
        assert node._get_nested_value(msg, 'nothing.at.all') is None
        assert node._get_nested_value(msg, '') is None

    def test_set_creates_intermediate_dicts(self, node):
        msg = {}
        assert node._set_nested_value(msg, 'payload.image.width', 640) is True
        assert msg == {'payload': {'image': {'width': 640}}}

    def test_set_creates_and_pads_lists(self, node):
        msg = {}
        node._set_nested_value(msg, 'items[2].name', 'third')
        assert isinstance(msg['items'], list)
        assert len(msg['items']) == 3
        assert msg['items'][2] == {'name': 'third'}
        assert msg['items'][0] == {}  # padded with empty dicts

    def test_set_final_key_indexing_pads_with_none(self, node):
        msg = {}
        node._set_nested_value(msg, 'arr[1]', 'x')
        assert msg['arr'] == [None, 'x']

    def test_set_msg_prefix_stripped(self, node):
        msg = {}
        node._set_nested_value(msg, 'msg.payload', 5)
        assert msg == {'payload': 5}

    def test_set_overwrites_existing(self, node):
        msg = {'payload': {'v': 1}}
        node._set_nested_value(msg, 'payload.v', 2)
        assert msg['payload']['v'] == 2


# ------------------------------------------------------------------
# Config coercion helpers + configure()
# ------------------------------------------------------------------

class TestConfigHelpers:

    def test_get_config_bool_string_coercion(self):
        node = BaseNode()
        node.config.update({
            'a': 'true', 'b': '1', 'c': 'yes', 'd': 'TRUE',
            'e': 'false', 'f': '0', 'g': 'no', 'h': True, 'i': 0,
        })
        assert node.get_config_bool('a') is True
        assert node.get_config_bool('b') is True
        assert node.get_config_bool('c') is True
        assert node.get_config_bool('d') is True
        assert node.get_config_bool('e') is False
        assert node.get_config_bool('f') is False
        assert node.get_config_bool('g') is False
        assert node.get_config_bool('h') is True
        assert node.get_config_bool('i') is False
        assert node.get_config_bool('missing', default=True) is True
        assert node.get_config_bool('missing') is False

    def test_get_config_int_and_float_coercion(self):
        node = BaseNode()
        node.config.update({'n': '5', 'm': 7, 'f': '2.5', 'g': 3.25})
        assert node.get_config_int('n') == 5
        assert node.get_config_int('m') == 7
        assert node.get_config_int('missing', default=9) == 9
        assert node.get_config_float('f') == 2.5
        assert node.get_config_float('g') == 3.25
        assert node.get_config_float('missing', default=1.5) == 1.5

    def test_configure_updates_drop_while_busy(self):
        node = BaseNode()
        assert node.drop_while_busy is True  # default

        node.configure({MessageKeys.DROP_MESSAGES: False})
        assert node.drop_while_busy is False

        node.configure({MessageKeys.DROP_MESSAGES: 'true'})
        assert node.drop_while_busy is True

        node.configure({MessageKeys.DROP_MESSAGES: 'false'})
        assert node.drop_while_busy is False

        # Unrelated configure keeps the previously-configured value
        node.configure({'other': 1})
        assert node.drop_while_busy is False
        assert node.config['other'] == 1

    def test_configure_merges_config(self):
        node = BaseNode()
        node.configure({'a': 1})
        node.configure({'b': 2})
        assert node.config['a'] == 1 and node.config['b'] == 2


# ------------------------------------------------------------------
# sort_msg_keys helper
# ------------------------------------------------------------------

def test_sort_msg_keys_underscore_first_then_alpha():
    msg = {'topic': 1, '_msgid': 2, 'payload': 3, '_age': 4, 'alpha': 5}
    assert list(sort_msg_keys(msg).keys()) == [
        '_age', '_msgid', 'alpha', 'payload', 'topic']

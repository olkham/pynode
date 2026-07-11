"""Tests for CounterNode SSE change-detection (get_count_sse)."""

from pynode.nodes.CounterNode.counter_node import CounterNode


def _make_msg(payload=None):
    return {'payload': payload if payload is not None else {'x': 1}, 'topic': 'test'}


class TestCounterSseChangeDetection:
    def test_first_poll_emits_current_count(self):
        node = CounterNode(node_id='c1', name='counter')
        result = node.get_count_sse()
        assert result == {'display': '0', 'count': 0}

    def test_unchanged_count_returns_none(self):
        node = CounterNode(node_id='c1', name='counter')
        assert node.get_count_sse() is not None
        # No increments in between -> nothing new to broadcast
        assert node.get_count_sse() is None
        assert node.get_count_sse() is None

    def test_emits_again_after_increment(self):
        node = CounterNode(node_id='c1', name='counter')
        assert node.get_count_sse() == {'display': '0', 'count': 0}
        assert node.get_count_sse() is None

        node.on_input(_make_msg())
        result = node.get_count_sse()
        assert result == {'display': '1', 'count': 1}
        # And back to suppressed until the next change
        assert node.get_count_sse() is None

    def test_multiple_increments_between_polls_emit_latest(self):
        node = CounterNode(node_id='c1', name='counter')
        node.get_count_sse()

        for _ in range(5):
            node.on_input(_make_msg())
        assert node.get_count_sse() == {'display': '5', 'count': 5}
        assert node.get_count_sse() is None

    def test_reset_emits_new_value(self):
        node = CounterNode(node_id='c1', name='counter')
        node.on_input(_make_msg())
        node.on_input(_make_msg())
        assert node.get_count_sse() == {'display': '2', 'count': 2}
        assert node.get_count_sse() is None

        node.reset_counter()
        assert node.get_count_sse() == {'display': '0', 'count': 0}
        assert node.get_count_sse() is None

    def test_throttle_lowered_with_change_detection(self):
        # Guard against regressing back to a slow throttle: with
        # change-detection in place the handler is cheap, so the declared
        # throttle should be small (or absent).
        handler = CounterNode.sse_handlers[0]
        assert handler['handler'] == 'get_count_sse'
        assert handler.get('throttle') is None or handler['throttle'] <= 0.1

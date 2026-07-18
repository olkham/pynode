"""VideoReaderNode tests: playback, transport controls, threading and
API registration.

A tiny synthetic video is generated with cv2.VideoWriter into a tmp dir
(mp4/'mp4v' preferred, .avi/'MJPG' fallback when the mp4 codec is missing).
Frames are collected through the conftest _SinkNode, which receives messages
synchronously (on_input_direct), so no engine or worker-thread timing is
involved. Every started playback thread is halted/joined in fixture teardown.
"""

import base64
import time

import cv2
import numpy as np
import pytest

from pynode.nodes import image_utils
from pynode.nodes.base_node import MessageKeys
from pynode.nodes.VideoReaderNode.video_reader_node import VideoReaderNode

N_FRAMES = 10
SIZE = 64
STEP = 25  # gray-level step per frame; frame i is solid (i * STEP)


def _wait_until(cond, timeout=8.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return cond()


def _decode_mean(image_payload):
    """Decode the image payload (raw numpy dict or jpeg-base64 dict, the two
    formats VideoReaderNode can emit depending on 'encode_jpeg') and return
    its mean intensity."""
    img, format_type = image_utils.decode_image(image_payload)
    assert img is not None, f"failed to decode image payload (format_type={format_type})"
    return float(img.mean())


@pytest.fixture(scope='module')
def video_path(tmp_path_factory):
    """Synthesize a small solid-gray-per-frame video in a tmp dir."""
    tmp = tmp_path_factory.mktemp('videos')
    for suffix, fourcc in (('.mp4', 'mp4v'), ('.avi', 'MJPG')):
        path = tmp / f'clip{suffix}'
        writer = cv2.VideoWriter(str(path),
                                 cv2.VideoWriter_fourcc(*fourcc),
                                 30.0, (SIZE, SIZE))
        if not writer.isOpened():
            writer.release()
            continue
        for i in range(N_FRAMES):
            writer.write(np.full((SIZE, SIZE, 3), i * STEP, dtype=np.uint8))
        writer.release()

        cap = cv2.VideoCapture(str(path))
        ok = cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == N_FRAMES
        cap.release()
        if ok:
            return str(path)
    pytest.skip('No usable video codec (mp4v/MJPG) in this environment')


@pytest.fixture
def vr(node_classes, video_path):
    """A VideoReaderNode wired to a synchronous sink, cleaned up on teardown."""
    node = VideoReaderNode(node_id='vr-test', name='vr')
    sink = node_classes['sink'](node_id='vr-sink', name='sink')
    node.connect(sink)
    node.configure({MessageKeys.VIDEO.SOURCE: video_path})
    try:
        yield node, sink
    finally:
        node.on_stop()
        thread = node._play_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


class TestPlayback:

    def test_play_emits_all_frames_in_order_then_ends(self, vr, video_path):
        node, sink = vr
        node.play_pause()

        assert _wait_until(lambda: len(sink.received) == N_FRAMES
                           and not node._playing)
        # loop=false: nothing more is emitted after the end
        time.sleep(0.2)
        assert len(sink.received) == N_FRAMES
        assert node._play_thread is None or not node._play_thread.is_alive()

        for i, msg in enumerate(sink.received):
            assert msg[MessageKeys.TOPIC] == 'video/frame'
            assert msg['frame_count'] == i
            payload = msg[MessageKeys.PAYLOAD]
            assert payload['frame'] == i
            assert payload['total_frames'] == N_FRAMES
            assert payload[MessageKeys.VIDEO.SOURCE] == video_path

            image = payload[MessageKeys.IMAGE.PATH]
            # Default output is raw numpy (no JPEG encoding overhead) - see
            # TestOutputFormat below for the encode_jpeg=True path.
            assert image[MessageKeys.IMAGE.FORMAT] == 'bgr'
            assert image[MessageKeys.IMAGE.ENCODING] == 'numpy'
            assert isinstance(image[MessageKeys.IMAGE.DATA], np.ndarray)
            assert image[MessageKeys.IMAGE.WIDTH] == SIZE
            assert image[MessageKeys.IMAGE.HEIGHT] == SIZE
            assert abs(_decode_mean(image) - i * STEP) < 12

    def test_pause_stops_emission(self, vr):
        node, sink = vr
        node.configure({MessageKeys.CAMERA.FPS: 10})  # slow playback
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= 2)

        node.play_pause()  # pause (halts + joins the playback thread)
        assert node._playing is False
        count = len(sink.received)
        time.sleep(0.3)
        assert len(sink.received) == count

    def test_resume_continues_from_pause_position(self, vr):
        node, sink = vr
        node.configure({MessageKeys.CAMERA.FPS: 10})
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= 2)
        node.play_pause()  # pause
        last = sink.received[-1][MessageKeys.PAYLOAD]['frame']

        node.play_pause()  # resume
        assert _wait_until(lambda: len(sink.received) > last + 1)
        node.play_pause()  # pause again
        frames = [m[MessageKeys.PAYLOAD]['frame'] for m in sink.received]
        assert frames == list(range(len(frames)))  # no skips, no repeats

    def test_loop_true_wraps_to_first_frame(self, vr):
        node, sink = vr
        node.configure({MessageKeys.VIDEO.LOOP: True})
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= N_FRAMES + 3)
        node.play_pause()  # pause

        frames = [m[MessageKeys.PAYLOAD]['frame'] for m in sink.received]
        assert frames[:N_FRAMES] == list(range(N_FRAMES))
        assert frames[N_FRAMES] == 0  # wrapped


class TestTransportControls:

    def test_step_next_moves_exactly_one_frame(self, vr):
        node, sink = vr
        node.step_next()
        assert len(sink.received) == 1
        assert sink.received[0][MessageKeys.PAYLOAD]['frame'] == 0

        node.step_next()
        assert len(sink.received) == 2
        assert sink.received[1][MessageKeys.PAYLOAD]['frame'] == 1
        assert abs(_decode_mean(
            sink.received[1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]
        ) - STEP) < 12

    def test_step_prev_moves_exactly_one_frame_back(self, vr):
        node, sink = vr
        node.step_next()  # frame 0
        node.step_next()  # frame 1
        node.step_next()  # frame 2
        node.step_prev()  # back to frame 1
        assert len(sink.received) == 4
        assert sink.received[-1][MessageKeys.PAYLOAD]['frame'] == 1
        assert abs(_decode_mean(
            sink.received[-1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]
        ) - STEP) < 12

        # step_prev clamps at the first frame
        node.step_prev()  # frame 0
        node.step_prev()  # stays at frame 0
        assert sink.received[-2][MessageKeys.PAYLOAD]['frame'] == 0
        assert sink.received[-1][MessageKeys.PAYLOAD]['frame'] == 0

    def test_steps_ignored_while_playing(self, vr):
        node, sink = vr
        node.configure({MessageKeys.CAMERA.FPS: 5})
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= 1)
        frames_before = [m[MessageKeys.PAYLOAD]['frame'] for m in sink.received]
        node.step_next()
        node.step_prev()
        node.play_pause()  # pause
        frames = [m[MessageKeys.PAYLOAD]['frame'] for m in sink.received]
        # Steps were no-ops: still a strictly increasing playback sequence
        assert frames == list(range(len(frames)))
        assert len(frames) >= len(frames_before)

    def test_stop_resets_to_first_frame(self, vr):
        node, sink = vr
        node.step_next()  # 0
        node.step_next()  # 1
        node.step_next()  # 2
        node.stop()
        assert node._frame_index == 0

        node.step_next()
        assert sink.received[-1][MessageKeys.PAYLOAD]['frame'] == 0
        assert abs(_decode_mean(
            sink.received[-1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]
        )) < 12

    def test_stop_during_playback_halts_thread(self, vr):
        node, sink = vr
        node.configure({MessageKeys.CAMERA.FPS: 10})
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= 1)

        node.stop()
        assert node._playing is False
        assert node._play_thread is None or not node._play_thread.is_alive()
        count = len(sink.received)
        time.sleep(0.3)
        assert len(sink.received) == count
        assert node._frame_index == 0


class TestOutputFormat:
    """VideoReaderNode.DEFAULT_CONFIG[encode_jpeg] is False: raw numpy is the
    default payload format (mirrors CameraNode's ENCODE_JPEG toggle); JPEG
    base64 is opt-in. Frames are read via step_next() -> _emit_frame_at(),
    so no playback thread is ever started for these tests."""

    def test_default_config_has_encode_jpeg_false(self):
        assert VideoReaderNode.DEFAULT_CONFIG[MessageKeys.CAMERA.ENCODE_JPEG] is False

    def test_default_output_is_raw_numpy(self, vr):
        node, sink = vr
        node.step_next()
        assert len(sink.received) == 1
        image = sink.received[-1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]

        assert image[MessageKeys.IMAGE.FORMAT] == 'bgr'
        assert image[MessageKeys.IMAGE.ENCODING] == 'numpy'
        data = image[MessageKeys.IMAGE.DATA]
        assert isinstance(data, np.ndarray)
        assert data.shape == (SIZE, SIZE, 3)
        assert image[MessageKeys.IMAGE.WIDTH] == SIZE
        assert image[MessageKeys.IMAGE.HEIGHT] == SIZE

    def test_encode_jpeg_true_outputs_jpeg_base64(self, vr):
        node, sink = vr
        node.configure({MessageKeys.CAMERA.ENCODE_JPEG: True})
        node.step_next()
        assert len(sink.received) == 1
        image = sink.received[-1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]

        assert image[MessageKeys.IMAGE.FORMAT] == 'jpeg'
        assert image[MessageKeys.IMAGE.ENCODING] == 'base64'
        data = image[MessageKeys.IMAGE.DATA]
        assert isinstance(data, str)  # base64 text, not raw bytes/ndarray

        raw = base64.b64decode(data)
        decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape == (SIZE, SIZE, 3)

    def test_jpeg_quality_only_applies_when_encoding_is_enabled(self, vr):
        """jpeg_quality is read but has no effect on the raw-numpy default;
        it only feeds cv2.imencode() when encode_jpeg=True."""
        node, sink = vr
        node.configure({MessageKeys.CAMERA.JPEG_QUALITY: 1})  # would visibly degrade JPEG
        node.step_next()
        image = sink.received[-1][MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH]
        assert image[MessageKeys.IMAGE.ENCODING] == 'numpy'
        assert isinstance(image[MessageKeys.IMAGE.DATA], np.ndarray)


class TestLifecycle:

    def test_on_start_does_not_open_capture_or_play(self, vr):
        node, sink = vr
        node.on_start()
        time.sleep(0.1)
        assert node._cap is None
        assert node._playing is False
        assert node._play_thread is None
        assert sink.received == []

    def test_on_stop_joins_playback_thread_and_releases_capture(self, vr):
        node, sink = vr
        node.on_start()
        node.configure({MessageKeys.CAMERA.FPS: 10})
        node.play_pause()
        assert _wait_until(lambda: len(sink.received) >= 1)
        thread = node._play_thread
        assert thread is not None and thread.is_alive()

        node.on_stop()
        assert node._playing is False
        assert not thread.is_alive()
        assert node._play_thread is None
        assert node._cap is None

    def test_sse_position_reports_only_on_change(self, vr):
        node, sink = vr
        first = node.get_position_sse()
        assert first == {'frame': 0, 'total': 0, 'playing': False}
        assert node.get_position_sse() is None  # unchanged

        node.step_next()  # frame 0 emitted; totals now known
        update = node.get_position_sse()
        assert update == {'frame': 0, 'total': N_FRAMES, 'playing': False}
        assert node.get_position_sse() is None


class TestApiIntegration:

    def test_registered_in_node_types_with_transport_ui(self, api_client):
        types = api_client.get('/api/node-types').get_json()
        entry = next((t for t in types if t['type'] == 'VideoReaderNode'), None)
        assert entry is not None, 'VideoReaderNode not auto-discovered'
        assert entry['name'] == 'Video Reader'
        assert entry['category'] == 'input'
        assert entry['inputCount'] == 0
        assert entry['outputCount'] == 1
        assert entry['uiComponent'] == 'transport-controls'
        actions = [b['action'] for b in entry['uiComponentConfig']['buttons']]
        assert actions == ['step_prev', 'play_pause', 'stop', 'step_next']

    def test_declared_actions_reachable_undeclared_404(self, api_client,
                                                       video_path):
        resp = api_client.post('/api/workflows', json={'name': 'vr wf'})
        wid = resp.get_json()['id']
        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [{'id': 'vr-api', 'type': 'VideoReaderNode',
                            'name': 'vr',
                            'config': {MessageKeys.VIDEO.SOURCE: video_path},
                            'enabled': True}],
        })
        assert resp.status_code == 200

        try:
            # Declared actions respond 200
            for action in ('play_pause', 'play_pause', 'step_next', 'stop'):
                resp = api_client.post(f'/api/nodes/vr-api/{action}')
                assert resp.status_code == 200, (action, resp.get_json())
                assert resp.get_json()['success'] is True

            # Undeclared / private methods are rejected with 404
            for bad in ('_ensure_capture', 'handle_upload_video', 'on_stop'):
                resp = api_client.post(f'/api/nodes/vr-api/{bad}')
                assert resp.status_code == 404
        finally:
            node = api_client.manager.deployed_engines[wid].get_node('vr-api')
            if node is not None:
                node.on_stop()

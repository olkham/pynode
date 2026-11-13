"""Appearance-based re-identification built on Roboflow's ``reid`` package.

A tracker's ids only last while it can follow an object from one frame to the
next. This node gives each detection an *identity* derived from what it looks
like, so the same person keeps the same number after leaving and re-entering
the frame, after a long occlusion, or when walking from one camera to another.
"""

import logging
import threading
import time
from typing import Any

import numpy as np

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    REID_ID_KEY,
    import_supervision,
    reid_missing_message,
    reid_model_options,
    resolve_torch_device,
    supervision_missing_message,
    to_sv,
    use_pynode_reid_cache,
    write_back,
)

from .reid_gallery import IdentityGallery, get_shared_gallery, l2_normalize

logger = logging.getLogger(__name__)

# One loaded model per (source, device) for the whole process: four camera
# flows using the same model share one copy of the weights. Each entry is
# (model, lock) - the lock serialises inference on that model.
_models: dict[tuple[str, str], tuple[Any, threading.Lock]] = {}
_models_lock = threading.Lock()

# Track -> identity entries kept per node before the oldest are dropped.
_MAX_TRACK_MAP = 4096

_info = Info()
_info.add_text(
    "Gives every detection an identity based on its appearance, using a person "
    "re-identification model from Roboflow's reid package. Unlike a track ID, the "
    "identity survives leaving the frame, long occlusions and - with a shared "
    "gallery - moving between cameras."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.image and payload.detections. Works best after an "
                 "SV Tracker, which lets the node embed each object only occasionally")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Same message; each matched detection gains reid_id. Also payload.identities "
                  "(one entry per identified box) and payload.identity_count (gallery size)"),
    ("Output 1:", "One message per identity event: 'new' (first time seen) or 'reidentified' "
                  "(seen again after an absence, possibly by another camera)")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Model:", "Pretrained Re-ID model. Weights download on first use into the models directory"),
    ("Classes:", "Comma list of class names (or ids) to identify. The bundled models are trained "
                 "on people. Blank = every detection"),
    ("Match Distance:", "Maximum cosine distance (0-1) to an existing identity that still counts "
                        "as the same one. Lower = stricter, more new identities (default 0.3)"),
    ("Gallery:", "Name of a shared identity gallery. Nodes using the same name and model share "
                 "identities - give every camera the same name for cross-camera Re-ID. Blank = "
                 "private to this node"),
    ("Use As Track ID:", "Replace track_id with the identity so annotators, zones and counters "
                         "downstream follow the stable identity"),
    ("Refresh Interval:", "Frames between appearance updates for an object the tracker is "
                          "already following. Higher = faster (default 10)"),
    ("Forget After:", "Seconds an identity is remembered without being seen. 0 = until reset"),
    ("Max Identities:", "Gallery size limit; the least recently seen identity is dropped first"),
    ("Min Box Size:", "Boxes narrower or shorter than this many pixels are not identified"),
    ("Include Embeddings:", "Attach the raw embedding vector to each detection (large - for "
                            "vector databases or custom matching)"),
    ("Reset Gallery:", "Forget all identities and restart from 1")
)
_info.add_header("Notes")
_info.add_bullets(
    ("Tuning:", "If one person keeps getting new identities, raise Match Distance. If different "
                "people merge into one identity, lower it."),
    ("Without a tracker:", "Every detection is embedded and matched on every frame. It works, "
                           "but is slower and identities can flicker between similar people."),
    ("Lifetime:", "A named gallery lives until Reset or until PyNode restarts. It is not saved to disk.")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("reid:", 'pip install "pynode-flow[reid]"')
)


def _parse_class_list(value: Any) -> set[str]:
    return {part.strip().lower() for part in str(value or '').split(',') if part.strip()}


class SupervisionReIDNode(BaseNode):
    """Appearance re-identification with a shareable identity gallery."""

    info = str(_info)
    display_name = 'SV Re-ID'
    icon = '🪪'
    category = 'supervision'
    color = '#5C2D91'
    border_color = '#3F1D63'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 2

    actions = ['reset']

    DEFAULT_CONFIG = {
        'model': 'osnet_x1_0_msmt17_combineall',
        'custom_model': '',
        'device': 'auto',
        'classes': 'person',
        'match_distance': '0.3',
        'gallery': '',
        'use_as_track_id': False,
        'refresh_interval': '10',
        'ttl_seconds': '0',
        'max_identities': '1000',
        'min_box_size': '16',
        'include_embeddings': False,
    }

    properties = [
        {
            'name': 'model',
            'label': 'Model',
            'type': 'select',
            'options': reid_model_options() + [{'value': 'custom', 'label': 'Custom (path / URL)'}],
            'default': DEFAULT_CONFIG['model'],
        },
        {
            'name': 'custom_model',
            'label': 'Custom Model Source',
            'type': 'text',
            'placeholder': 'hf://org/repo, https://..., or a local export folder',
            'default': DEFAULT_CONFIG['custom_model'],
            'help': 'Anything reid.ReIDModel.from_pretrained accepts',
            'showIf': {'model': 'custom'},
        },
        {
            'name': 'device',
            'label': 'Device',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto'},
                {'value': 'cpu', 'label': 'CPU'},
                {'value': 'cuda', 'label': 'CUDA (GPU)'},
            ],
            'default': DEFAULT_CONFIG['device'],
        },
        {
            'name': 'classes',
            'label': 'Classes',
            'type': 'text',
            'placeholder': 'person',
            'default': DEFAULT_CONFIG['classes'],
            'help': 'Comma list of class names or ids to identify. Blank = all',
        },
        {
            'name': 'match_distance',
            'label': 'Match Distance',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['match_distance'],
            'default': DEFAULT_CONFIG['match_distance'],
            'help': 'Max cosine distance (0-1) to count as the same identity. Lower = stricter',
        },
        {
            'name': 'gallery',
            'label': 'Gallery',
            'type': 'text',
            'placeholder': 'private to this node',
            'default': DEFAULT_CONFIG['gallery'],
            'help': 'Nodes with the same gallery name share identities (cross-camera Re-ID)',
        },
        {
            'name': 'use_as_track_id',
            'label': 'Use As Track ID',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['use_as_track_id'],
            'help': 'Replace track_id with the identity for downstream nodes',
        },
        {
            'name': 'refresh_interval',
            'label': 'Refresh Interval (frames)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['refresh_interval'],
            'default': DEFAULT_CONFIG['refresh_interval'],
            'help': 'Frames between appearance updates for an already-tracked object',
        },
        {
            'name': 'ttl_seconds',
            'label': 'Forget After (seconds)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['ttl_seconds'],
            'default': DEFAULT_CONFIG['ttl_seconds'],
            'help': '0 = remember until reset',
        },
        {
            'name': 'max_identities',
            'label': 'Max Identities',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['max_identities'],
            'default': DEFAULT_CONFIG['max_identities'],
        },
        {
            'name': 'min_box_size',
            'label': 'Min Box Size (px)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['min_box_size'],
            'default': DEFAULT_CONFIG['min_box_size'],
        },
        {
            'name': 'include_embeddings',
            'label': 'Include Embeddings',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['include_embeddings'],
        },
        {
            'name': 'reset',
            'label': 'Reset Gallery',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_reid"):
        self._model = None
        self._model_lock: threading.Lock | None = None
        self._model_key: tuple[str, str] | None = None
        self._loading = False
        self._load_failed_for: tuple[str, str] | None = None
        self._private_gallery = IdentityGallery()
        # track_id -> (identity, frame index of the last appearance update)
        self._track_identity: dict[int, tuple[int, int]] = {}
        self._frame_index = 0
        self._missing_reported = False
        self._image_missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _float(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int(self, key: str, default: int) -> int:
        try:
            return int(float(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _model_source(self) -> str:
        model = str(self.config.get('model', '') or '').strip()
        if model == 'custom':
            return str(self.config.get('custom_model', '') or '').strip()
        return model

    def _gallery(self) -> IdentityGallery:
        name = str(self.config.get('gallery', '') or '').strip()
        if not name:
            return self._private_gallery
        return get_shared_gallery(name, self._model_source())

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def _load_model(self, source: str, device: str):
        """Load a Re-ID model. Separate so tests can substitute an encoder."""
        from reid import ReIDModel  # type: ignore

        use_pynode_reid_cache()
        return ReIDModel.from_pretrained(source, device=device)

    def _load_worker(self, key: tuple[str, str]):
        source, device = key
        try:
            with _models_lock:
                entry = _models.get(key)
            if entry is None:
                logger.info(f"SV Re-ID ({self.id}): loading model '{source}' on {device}")
                model = self._load_model(source, device)
                with _models_lock:
                    entry = _models.setdefault(key, (model, threading.Lock()))
            self._model, self._model_lock = entry
            self._model_key = key
            logger.info(f"SV Re-ID ({self.id}): model '{source}' ready")
        except ImportError:
            self._load_failed_for = key
            self.report_error(reid_missing_message())
        except Exception as e:
            self._load_failed_for = key
            logger.error(f"SV Re-ID ({self.id}): could not load '{source}': {e}", exc_info=True)
            self.report_error(f"Could not load Re-ID model '{source}': {e}")
        finally:
            self._loading = False

    def _ensure_model(self) -> bool:
        """Return True when the configured model is ready.

        Loading (which may download weights) runs on a background thread so
        the flow keeps moving; frames pass through unidentified meanwhile.
        """
        source = self._model_source()
        if not source:
            if not self._missing_reported:
                self.report_error("No Re-ID model configured")
                self._missing_reported = True
            return False

        device, warning = resolve_torch_device(self.config.get('device', 'auto'))
        key = (source, device)
        if self._model is not None and self._model_key == key:
            return True
        if self._loading or self._load_failed_for == key:
            return False

        if warning:
            self.report_error(warning)
        self._loading = True
        self._model = None
        threading.Thread(target=self._load_worker, args=(key,), daemon=True,
                         name=f"reid-load-{self.id}").start()
        return False

    def on_start(self):
        # Track ids restart whenever the upstream tracker does, so stale
        # track -> identity links must not survive a redeploy.
        self._track_identity.clear()
        self._frame_index = 0
        self._load_failed_for = None
        super().on_start()

    def reset(self):
        """Forget every identity in this node's gallery (UI action)."""
        self._gallery().reset()
        self._track_identity.clear()
        logger.info(f"SV Re-ID ({self.id}): gallery reset")
        return {'status': 'reset'}

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def _eligible(self, detections, frame_shape) -> np.ndarray:
        """Boolean mask of detections worth identifying."""
        count = len(detections)
        mask = np.ones(count, dtype=bool)

        min_size = max(self._int('min_box_size', 16), 1)
        height, width = frame_shape[:2]
        xyxy = detections.xyxy
        widths = np.clip(xyxy[:, 2], 0, width) - np.clip(xyxy[:, 0], 0, width)
        heights = np.clip(xyxy[:, 3], 0, height) - np.clip(xyxy[:, 1], 0, height)
        mask &= (widths >= min_size) & (heights >= min_size)

        wanted = _parse_class_list(self.config.get('classes'))
        if wanted:
            names = detections.data.get('class_name') if detections.data else None
            for i in range(count):
                tokens = set()
                if names is not None and i < len(names):
                    tokens.add(str(names[i]).lower())
                if detections.class_id is not None:
                    tokens.add(str(int(detections.class_id[i])))
                if not (tokens & wanted):
                    mask[i] = False
        return mask

    def _embed(self, detections, frame) -> np.ndarray:
        model: Any = self._model
        with self._model_lock or threading.Lock():
            embeddings = model.extract_embeddings(detections, frame)
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or len(embeddings) != len(detections):
            raise ValueError(
                f"Re-ID model returned shape {embeddings.shape} for {len(detections)} detections")
        return l2_normalize(embeddings)

    def _identify(self, detections, frame) -> tuple[np.ndarray, list[dict[str, Any]], dict[int, np.ndarray]]:
        """Assign an identity to each eligible detection.

        Returns:
            ``(reid_ids, events, embeddings)`` - ``reid_ids`` is aligned with
            ``detections`` (-1 = no identity); ``embeddings`` maps detection
            index to the unit embedding computed this frame.
        """
        count = len(detections)
        reid_ids = np.full(count, -1, dtype=int)
        events: list[dict[str, Any]] = []
        computed: dict[int, np.ndarray] = {}
        if count == 0:
            return reid_ids, events, computed

        gallery = self._gallery()
        now = time.monotonic()
        source = self.name or self.id
        threshold = min(max(self._float('match_distance', 0.3), 0.0), 2.0)
        refresh = max(self._int('refresh_interval', 10), 1)
        always_embed = self.get_config_bool('include_embeddings', False)
        eligible = self._eligible(detections, frame.shape)
        track_ids = detections.tracker_id

        # 1. Objects the tracker is already following keep their identity.
        known: dict[int, int] = {}       # detection index -> identity
        to_embed: list[int] = []
        for i in np.flatnonzero(eligible):
            i = int(i)
            tid = int(track_ids[i]) if track_ids is not None else -1
            linked = self._track_identity.get(tid) if tid >= 0 else None
            if linked is not None and linked[0] in gallery:
                known[i] = linked[0]
                if always_embed or self._frame_index - linked[1] >= refresh:
                    to_embed.append(i)
            else:
                to_embed.append(i)

        if to_embed:
            unit = self._embed(detections[np.array(to_embed)], frame)
            computed = {idx: unit[row] for row, idx in enumerate(to_embed)}

        with gallery.lock:
            # Expire stale identities first so nothing is matched to them.
            gallery.prune(ttl_seconds=self._float('ttl_seconds', 0.0),
                          now=now, keep=set(known.values()))

            # 2. Everything else is matched against the gallery by appearance.
            #    An identity can only be one box per frame.
            unknown = [i for i in to_embed if i not in known]
            matches = gallery.match(
                np.stack([computed[i] for i in unknown]) if unknown else np.empty((0, 0), np.float32),
                threshold, exclude=set(known.values()))

            for i, (identity, distance) in zip(unknown, matches):
                tid = int(track_ids[i]) if track_ids is not None else -1
                if identity is None:
                    identity = gallery.add(computed[i], source=source, now=now)
                    events.append(self._event('new', identity, tid, detections, i, None, None, None))
                else:
                    seen_at, seen_by = gallery.last_seen(identity)
                    absent = (now - seen_at) if seen_at is not None else 0.0
                    # A tracked object is announced once (its track is new to
                    # this identity). Untracked detections are re-matched on
                    # every frame, so only a real absence is an event.
                    if tid >= 0 or absent >= 1.0 or (seen_by and seen_by != source):
                        events.append(self._event(
                            'reidentified', identity, tid, detections, i, distance, absent, seen_by))
                    gallery.update(identity, computed[i], source=source, now=now)
                known[i] = identity
                if tid >= 0:
                    self._track_identity[tid] = (identity, self._frame_index)

            # 3. Refresh the appearance of already-linked objects.
            for i, identity in known.items():
                if i in unknown:
                    continue
                if i in computed:
                    gallery.update(identity, computed[i], source=source, now=now)
                    # Only tracked objects reach here, so track_ids exists.
                    tid = int(track_ids[i]) if track_ids is not None else -1
                    self._track_identity[tid] = (identity, self._frame_index)
                else:
                    gallery.touch(identity, source=source, now=now)

            # Enforce the size cap after this frame's additions, never
            # dropping an identity that is on screen right now.
            gallery.prune(max_identities=self._int('max_identities', 1000),
                          now=now, keep=set(known.values()))

        for i, identity in known.items():
            reid_ids[i] = identity

        if len(self._track_identity) > _MAX_TRACK_MAP:
            # Drop the links that were refreshed longest ago.
            keep = sorted(self._track_identity.items(), key=lambda kv: kv[1][1])[_MAX_TRACK_MAP // 2:]
            self._track_identity = dict(keep)

        return reid_ids, events, computed

    def _event(self, kind, identity, track_id, detections, index, distance, absent, seen_by) -> dict[str, Any]:
        names = detections.data.get('class_name') if detections.data else None
        event: dict[str, Any] = {
            'event': kind,
            'reid_id': int(identity),
            'bbox': [float(v) for v in detections.xyxy[index]],
            'class_name': str(names[index]) if names is not None and index < len(names) else '',
            'source': self.name or self.id,
            'gallery': str(self.config.get('gallery', '') or ''),
        }
        if track_id >= 0:
            event['track_id'] = track_id
        if distance is not None:
            event['distance'] = round(float(distance), 4)
        if absent is not None:
            event['absent_seconds'] = round(float(absent), 2)
        if seen_by:
            event['previous_source'] = seen_by
        return event

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def on_input(self, msg, input_index=0):
        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict):
            self.send(msg)
            return

        if import_supervision() is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            self.send(msg)
            return

        if not self._ensure_model():
            self.send(msg)
            return

        try:
            image = None
            if MessageKeys.IMAGE.PATH in payload:
                image, _ = self.decode_image(payload[MessageKeys.IMAGE.PATH])
            if image is None:
                if not self._image_missing_reported:
                    self.report_error("Re-ID needs payload.image to look at each detection")
                    self._image_missing_reported = True
                self.send(msg)
                return

            # Any: supervision's indexing is typed as a wide union.
            detections: Any = to_sv(payload)
            self._frame_index += 1
            reid_ids, events, embeddings = self._identify(detections, image)

            if len(detections) > 0:
                # Never mutate the upstream object in place: with fan-out the
                # same Detections may be travelling down another branch.
                detections = detections[np.arange(len(detections))]
                detections.data[REID_ID_KEY] = reid_ids
                if self.get_config_bool('use_as_track_id', False):
                    if detections.tracker_id is not None:
                        detections.data['local_track_id'] = detections.tracker_id.copy()
                    detections.tracker_id = reid_ids.copy()

            entries = write_back(detections, payload)
            if self.get_config_bool('include_embeddings', False):
                for index, embedding in embeddings.items():
                    entries[index]['embedding'] = [round(float(v), 6) for v in embedding]

            payload['identities'] = [
                {k: e[k] for k in ('reid_id', 'track_id', 'bbox', 'class_name') if k in e}
                for e in entries if 'reid_id' in e
            ]
            payload['identity_count'] = len(self._gallery())

            # Events first: send() contract forbids touching msg afterwards.
            for event in events:
                self.send({MessageKeys.PAYLOAD: event,
                           MessageKeys.TOPIC: f"reid/{event['event']}"}, output_index=1)
            self.send(msg, output_index=0)

        except Exception as e:
            logger.error(f"Error in SupervisionReIDNode: {e}", exc_info=True)
            self.report_error(f"Re-ID error: {e}")
            self.send(msg)

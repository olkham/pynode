"""Identity gallery used by the SV Re-ID node.

Pure numpy and free of torch / reid imports, so the matching logic is
unit-testable on a core install.

A gallery maps an integer identity to one appearance feature: the exponential
moving average of the unit-length embeddings seen for that identity. Matching
is by cosine distance (``1 - cosine similarity``; 0 = identical, 1 = unrelated).

Galleries are process-wide and looked up by name, so several SV Re-ID nodes -
one per camera, possibly in different workflows - can share one and hand the
same identity to a person who walks from one view into another.
"""

import threading
import time
from typing import Any

import numpy as np

_registry: dict[tuple[str, str], 'IdentityGallery'] = {}
_registry_lock = threading.Lock()


def get_shared_gallery(name: str, model: str) -> 'IdentityGallery':
    """Return the process-wide gallery for ``(name, model)``, creating it.

    The model is part of the key because embeddings from different models are
    not comparable (and usually differ in size).
    """
    key = (name, model)
    with _registry_lock:
        gallery = _registry.get(key)
        if gallery is None:
            gallery = _registry[key] = IdentityGallery()
        return gallery


def clear_shared_galleries():
    """Drop every shared gallery (test isolation)."""
    with _registry_lock:
        _registry.clear()


def l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    """Scale each row to unit length; all-zero rows stay zero."""
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim == 1:
        embeddings = embeddings[None, :]
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.maximum(norms, 1e-12)


def _assign(cost: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """One-to-one assignment of rows to columns with cost <= threshold."""
    if cost.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment  # type: ignore

        # Forbidden pairs get a large finite cost: the solver rejects inf.
        gated = np.where(cost <= threshold, cost, 1e6)
        rows, cols = linear_sum_assignment(gated)
        return [(int(r), int(c)) for r, c in zip(rows, cols) if cost[r, c] <= threshold]
    except ImportError:
        pairs = []
        used_rows: set[int] = set()
        used_cols: set[int] = set()
        for flat in np.argsort(cost, axis=None):
            r, c = divmod(int(flat), cost.shape[1])
            if cost[r, c] > threshold:
                break
            if r in used_rows or c in used_cols:
                continue
            used_rows.add(r)
            used_cols.add(c)
            pairs.append((r, c))
        return pairs


class IdentityGallery:
    """Thread-safe store of identity appearance features."""

    def __init__(self):
        self.lock = threading.RLock()
        self._features: dict[int, np.ndarray] = {}
        self._last_seen: dict[int, float] = {}
        self._last_source: dict[int, str] = {}
        self._next_id = 1

    def __len__(self) -> int:
        with self.lock:
            return len(self._features)

    def __contains__(self, identity: int) -> bool:
        with self.lock:
            return identity in self._features

    def ids(self) -> list[int]:
        with self.lock:
            return sorted(self._features)

    def reset(self):
        """Forget every identity and restart ids from 1."""
        with self.lock:
            self._features.clear()
            self._last_seen.clear()
            self._last_source.clear()
            self._next_id = 1

    def last_seen(self, identity: int) -> tuple[float | None, str | None]:
        """``(monotonic time, source)`` of the identity's latest sighting."""
        with self.lock:
            return self._last_seen.get(identity), self._last_source.get(identity)

    def prune(self, ttl_seconds: float = 0.0, max_identities: int = 0,
              now: float | None = None, keep: set[int] | None = None) -> list[int]:
        """Forget stale identities.

        Args:
            ttl_seconds: Drop identities unseen for longer than this (0 = never).
            max_identities: Keep at most this many, dropping the least recently
                seen first (0 = unlimited).
            now: Monotonic clock reading (defaults to ``time.monotonic()``).
            keep: Identities that must survive this call.

        Returns:
            The identities that were removed.
        """
        now = time.monotonic() if now is None else now
        keep = keep or set()
        removed: list[int] = []
        with self.lock:
            if ttl_seconds > 0:
                removed.extend(
                    i for i, seen in self._last_seen.items()
                    if now - seen > ttl_seconds and i not in keep)
            for identity in removed:
                self._drop(identity)

            if max_identities > 0 and len(self._features) > max_identities:
                oldest_first = sorted(self._last_seen, key=self._last_seen.__getitem__)
                excess = len(self._features) - max_identities
                for identity in oldest_first:
                    if excess <= 0:
                        break
                    if identity in keep:
                        continue
                    self._drop(identity)
                    removed.append(identity)
                    excess -= 1
        return removed

    def _drop(self, identity: int):
        self._features.pop(identity, None)
        self._last_seen.pop(identity, None)
        self._last_source.pop(identity, None)

    def match(self, embeddings: np.ndarray, threshold: float,
              exclude: set[int] | None = None) -> list[tuple[int | None, float | None]]:
        """Match unit embeddings against the gallery, one identity per row.

        Args:
            embeddings: ``(N, D)`` unit-length embeddings.
            threshold: Maximum cosine distance that still counts as a match.
            exclude: Identities that may not be assigned (already used in this
                frame).

        Returns:
            One ``(identity, distance)`` per row; ``(None, nearest_distance)``
            when nothing in the gallery is close enough (``nearest_distance`` is
            ``None`` for an empty gallery).
        """
        embeddings = np.asarray(embeddings, dtype=np.float32)
        results: list[tuple[int | None, float | None]] = [(None, None)] * len(embeddings)
        with self.lock:
            candidates = [
                i for i, feature in self._features.items()
                if (not exclude or i not in exclude) and feature.shape[0] == embeddings.shape[1]
            ]
            if not candidates or len(embeddings) == 0:
                return results
            features = np.stack([self._features[i] for i in candidates])

        cost = 1.0 - embeddings @ features.T
        nearest = cost.min(axis=1)
        results = [(None, float(d)) for d in nearest]
        for row, col in _assign(cost, threshold):
            results[row] = (candidates[col], float(cost[row, col]))
        return results

    def add(self, embedding: np.ndarray, source: str = '', now: float | None = None) -> int:
        """Register a new identity and return its id."""
        now = time.monotonic() if now is None else now
        with self.lock:
            identity = self._next_id
            self._next_id += 1
            self._features[identity] = np.asarray(embedding, dtype=np.float32).copy()
            self._last_seen[identity] = now
            self._last_source[identity] = source
            return identity

    def touch(self, identity: int, source: str = '', now: float | None = None):
        """Record a sighting without changing the appearance feature."""
        now = time.monotonic() if now is None else now
        with self.lock:
            if identity in self._features:
                self._last_seen[identity] = now
                self._last_source[identity] = source

    def update(self, identity: int, embedding: np.ndarray, alpha: float = 0.9,
               source: str = '', now: float | None = None):
        """Blend a new sighting into an identity's feature (EMA) and touch it."""
        with self.lock:
            feature = self._features.get(identity)
            if feature is None:
                return
            embedding = np.asarray(embedding, dtype=np.float32)
            if feature.shape == embedding.shape:
                blended = alpha * feature + (1.0 - alpha) * embedding
                self._features[identity] = l2_normalize(blended)[0]
            self.touch(identity, source, now)

    def snapshot(self) -> dict[str, Any]:
        """Summary for status / debugging."""
        with self.lock:
            return {'identity_count': len(self._features), 'ids': sorted(self._features)}

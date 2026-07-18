"""Process-wide, thread-safe message bus for the Link node family.

``LinkOutNode`` publishes messages to a named *channel*; every ``LinkInNode``
registered on the same channel receives a copy. Because a single Python
process hosts every workflow's engines (see ``WorkflowManager``), one
module-level :data:`link_bus` instance naturally spans workflows, letting a
node in one flow deliver to nodes in another.

Design notes
------------
* Registration is keyed by the *node instance*, so two different deployed
  engines (e.g. two workflows) each add their own ``LinkInNode`` and both
  receive published messages, while the working/deployed split never
  double-registers: only deployed engines have ``start()`` (and therefore
  ``on_start``) called on them, so only running instances ever register.
* :meth:`LinkBus.publish` snapshots the subscriber set under the lock and then
  delivers **outside** the lock. The lock is never held while a subscriber's
  ``send`` runs, so a same-channel Link-out -> Link-in cycle (the user's
  responsibility, as in Node-RED) cannot deadlock the bus.
* Delivery is guarded: a message is only handed to a subscriber whose engine
  is running and whose node is enabled. This uses the existing state
  (``node.enabled`` and ``node._workflow_engine.running``) rather than
  inventing a parallel notion of "alive".
"""

import threading


class LinkBus:
    """Channel -> set of subscribed ``LinkInNode`` instances, thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        # channel name -> set of LinkInNode instances
        self._subscribers = {}

    def register(self, channel, node):
        """Register ``node`` to receive messages published on ``channel``.

        An empty/whitespace channel is treated as unconfigured and ignored,
        so misconfigured nodes never accidentally form a broadcast group.
        """
        if not channel:
            return
        with self._lock:
            self._subscribers.setdefault(channel, set()).add(node)

    def unregister(self, channel, node):
        """Remove ``node`` from ``channel`` (no-op if not registered)."""
        if not channel:
            return
        with self._lock:
            subs = self._subscribers.get(channel)
            if subs is not None:
                subs.discard(node)
                if not subs:
                    del self._subscribers[channel]

    def publish(self, channel, msg):
        """Deliver ``msg`` to every eligible subscriber of ``channel``.

        The subscriber set is snapshotted under the lock; delivery happens
        afterwards with the lock released so a subscriber's ``send`` (which may
        re-enter the bus) can never deadlock it.
        """
        if not channel:
            return
        with self._lock:
            subs = self._subscribers.get(channel)
            targets = list(subs) if subs else []
        for node in targets:
            _deliver(node, msg)

    def subscriber_count(self, channel):
        """Number of registered subscribers on ``channel`` (for tests/introspection)."""
        with self._lock:
            subs = self._subscribers.get(channel)
            return len(subs) if subs else 0


def _deliver(node, msg):
    """Hand ``msg`` to a single subscriber, guarding against dead subscribers.

    Only delivers when the subscriber node is enabled and its owning engine is
    still running, so a node whose engine was stopped (even before its
    ``on_stop`` unregistered it) never receives. ``LinkInNode.receive`` routes
    the message through ``BaseNode.send``, which deep-copies it, isolating the
    two flows.
    """
    if not getattr(node, 'enabled', False):
        return
    engine = getattr(node, '_workflow_engine', None)
    if engine is None or not getattr(engine, 'running', False):
        return
    try:
        node.receive(msg)
    except Exception as exc:  # pragma: no cover - defensive
        report = getattr(node, 'report_error', None)
        if callable(report):
            report(f"Link delivery failed: {exc}")


# Process-wide singleton shared by every LinkOutNode / LinkInNode instance.
link_bus = LinkBus()

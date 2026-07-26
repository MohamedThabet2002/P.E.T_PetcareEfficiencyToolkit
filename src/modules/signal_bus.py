"""
Central application signal hub for the PET Application.

Coarse-grained domain events that pages emit to coordinate cross-page view
refreshes without each page needing to know about every other page.

The bus is additive: existing ``data_changed`` wiring in ``main_window`` is the
legacy path. New code can use ``SignalBus`` domain events (``visits_changed``,
``clients_changed``, ``supplies_changed``, ``receipts_changed``, ``login_changed``)
and get the same refresh behavior as the historical per-page wiring once the
relevant connections are made.

Emit via signal name string so subscribers can be introspected/refactored later:
    bus = SignalBus.instance()
    bus.emit_event("visits_changed")

Subscribe via decorator or connect:
    @bus.on("visits_changed")
    def refresh(dashboard=None): ...
"""

from PyQt5.QtCore import QObject, pyqtSignal

import inspect
import logging

logger = logging.getLogger(__name__)


def _accepts_payload(slot) -> bool:
    """True when ``slot`` can be called with one positional argument.

    Arity is decided by inspecting the signature *before* wiring, instead of
    optimistically calling with a payload and catching ``TypeError``. The old
    catch-and-retry pattern both executed a slot that raised ``TypeError``
    internally a second time and hid the real error.
    """
    try:
        params = list(inspect.signature(slot).parameters.values())
    except (TypeError, ValueError):
        # Some builtins/callables have no introspectable signature; assume the
        # payload is accepted (the historical behavior).
        return True
    for p in params:
        if p.kind == p.VAR_POSITIONAL:
            return True
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            return True
    return False


class SignalBus(QObject):
    """Singleton signal hub dispatching coarse domain events across pages."""

    # Coarse domain events (payload object optional; most refreshers take none).
    visits_changed = pyqtSignal(object)
    clients_changed = pyqtSignal(object)
    supplies_changed = pyqtSignal(object)
    receipts_changed = pyqtSignal(object)
    appointments_changed = pyqtSignal(object)
    login_changed = pyqtSignal(object)

    _EVENT_SIGNALS = {
        "visits_changed": "visits_changed",
        "clients_changed": "clients_changed",
        "supplies_changed": "supplies_changed",
        "receipts_changed": "receipts_changed",
        "appointments_changed": "appointments_changed",
        "login_changed": "login_changed",
    }

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._subscribers = {}

    @classmethod
    def instance(cls) -> "SignalBus":
        """Returns the process-wide signal bus singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def on(self, event_name: str, slot=None):
        """Registers ``slot`` (or decorates a callable) for ``event_name``.

        The subscriber receives a single optional payload argument (usually
        ``None``). Zero-argument callables are supported too.
        """
        if event_name not in self._EVENT_SIGNALS:
            raise ValueError(f"Unknown signal bus event: {event_name!r}")

        def decorator(func):
            self.connect(event_name, func)
            return func

        if slot is not None:
            return decorator(slot)
        return decorator

    def connect(self, event_name: str, slot):
        """Wires ``slot`` to the PyQt signal backing ``event_name``."""
        if event_name not in self._EVENT_SIGNALS:
            raise ValueError(f"Unknown signal bus event: {event_name!r}")
        signal = getattr(self, self._EVENT_SIGNALS[event_name])
        wants_payload = _accepts_payload(slot)

        def adapter(payload=None):
            try:
                if wants_payload:
                    slot(payload)
                else:
                    slot()
            except Exception:
                # PyQt aborts the whole process if a slot lets an exception
                # escape, so report it loudly via the log instead of crashing
                # (and never re-invoke the slot).
                logger.exception(
                    "SignalBus subscriber for %r raised", event_name)

        signal.connect(adapter)
        self._subscribers.setdefault(event_name, []).append(slot)
        return slot

    def emit_event(self, event_name: str, payload=None):
        """Emits a domain event to all subscribers (``payload`` default None)."""
        signal = getattr(self, self._EVENT_SIGNALS[event_name])
        signal.emit(payload)

    def subscribers(self, event_name: str):
        """Returns the registered callables for ``event_name`` (for tests)."""
        return list(self._subscribers.get(event_name, []))

    def reset(self):
        """Disconnects all subscribers (used by tests)."""
        for event_name, signal_name in self._EVENT_SIGNALS.items():
            signal = getattr(self, signal_name)
            try:
                signal.disconnect()
            except TypeError:
                pass  # no connections
        self._subscribers = {}
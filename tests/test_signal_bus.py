"""Unit tests for the central SignalBus (src/modules/signal_bus.py)."""

import pytest

from src.modules.signal_bus import SignalBus


@pytest.fixture(autouse=True)
def _fresh_bus():
    bus = SignalBus.instance()
    bus.reset()
    yield bus
    bus.reset()


class TestSignalBus:
    def test_emit_dispatches_to_subscribers(self):
        bus = SignalBus.instance()
        calls = []
        bus.on("visits_changed", lambda payload: calls.append(payload))
        bus.emit_event("visits_changed")
        bus.emit_event("visits_changed", payload="tag")
        assert calls == [None, "tag"]

    def test_decorator_style(self):
        bus = SignalBus.instance()
        calls = []
        @bus.on("clients_changed")
        def handler(payload):
            calls.append(payload)
        bus.emit_event("clients_changed")
        assert calls == [None]

    def test_zero_argument_slot(self):
        bus = SignalBus.instance()
        calls = []
        def handler():
            calls.append("fired")
        bus.on("supplies_changed", handler)
        bus.emit_event("supplies_changed")
        assert calls == ["fired"]

    def test_unknown_event_raises(self):
        bus = SignalBus.instance()
        with pytest.raises(ValueError):
            bus.on("does_not_exist", lambda p: None)
        with pytest.raises(ValueError):
            bus.connect("does_not_exist", lambda p: None)

    def test_subscribers_tracking(self):
        bus = SignalBus.instance()
        def h1(payload):
            pass
        def h2(payload):
            pass
        bus.on("receipts_changed", h1)
        bus.on("receipts_changed", h2)
        assert bus.subscribers("receipts_changed") == [h1, h2]

    def test_reset_clears_subscribers(self):
        bus = SignalBus.instance()
        bus.on("appointments_changed", lambda p: None)
        assert bus.subscribers("appointments_changed")
        bus.reset()
        assert bus.subscribers("appointments_changed") == []

    def test_singleton(self):
        assert SignalBus.instance() is SignalBus.instance()

    def test_events_do_not_cross_contaminate(self):
        bus = SignalBus.instance()
        visits = []
        clients = []
        bus.on("visits_changed", lambda p: visits.append(p))
        bus.on("clients_changed", lambda p: clients.append(p))
        bus.emit_event("visits_changed")
        assert len(visits) == 1 and not clients

    def test_slot_error_is_logged_and_not_re_run(self, caplog):
        """A slot that raises is reported, not swallowed or executed twice.

        The old adapter called the slot with a payload, caught ``TypeError``,
        then called it again with no arguments — running a slot that raised
        ``TypeError`` internally a second time (and hiding the real error).
        """
        bus = SignalBus.instance()
        calls = []

        def handler(payload=None):
            calls.append(payload)
            raise TypeError("boom inside the slot")

        bus.on("visits_changed", handler)
        # Must not escape (PyQt aborts the process on an unhandled slot error).
        bus.emit_event("visits_changed")

        assert calls == [None], "the slot body ran exactly once"
        assert any("visits_changed" in r.getMessage() for r in caplog.records)
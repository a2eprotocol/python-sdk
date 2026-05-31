"""Tests for DirectTransport — in-memory queue-based transport."""

import json
import pytest
from unittest.mock import MagicMock

from a2e.core.transports.direct import DirectTransport


class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


@pytest.fixture
def transport():
    return DirectTransport(logger=FakeLogger())


@pytest.fixture
def connected_pair():
    """Create two wired transports for testing bidirectional messaging."""
    t1 = DirectTransport(logger=FakeLogger())
    t2 = DirectTransport(logger=FakeLogger())
    t1.connect(t2)
    t2.connect(t1)
    return t1, t2


class TestDirectTransportInit:
    def test_default_queues_created(self, transport):
        assert transport._in_queue is not None
        assert transport._out_queue is not None

    def test_initial_not_alive(self, transport):
        assert transport.alive() is False

    def test_handler_and_out_handler_none(self, transport):
        assert transport._handler is None
        assert transport._out_handler is None


class TestTransportLifecycle:
    def test_start_marks_alive(self, transport):
        transport.start()
        assert transport.alive() is True

    def test_double_start_raises(self, transport):
        transport.start()
        with pytest.raises(RuntimeError, match="already started"):
            transport.start()

    def test_stop_marks_not_alive(self, transport):
        transport.start()
        transport.stop()
        assert transport.alive() is False

    def test_send_while_not_alive_raises(self, transport):
        with pytest.raises(RuntimeError, match="not alive"):
            transport.send("hello")


class TestConnect:
    def test_connect_wires_queues(self, connected_pair):
        t1, t2 = connected_pair
        # t1's _out_queue should be t2's _in_queue
        assert t1._out_queue is t2._in_queue
        assert t2._out_queue is t1._in_queue


class TestMessaging:
    def test_send_calls_out_handler(self, transport):
        transport.start()
        received = []

        def handler(msg):
            received.append(msg)

        transport.set_out_handler(handler)
        transport.send("hello")
        assert received == ["hello"]

    def test_read_loop_dispatches_to_handler(self, connected_pair):
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        # Send through t1 → should arrive at t2's handler
        t1._in_queue.put("hello from t1")
        import time
        time.sleep(0.2)
        assert len(received) >= 1

    def test_read_loop_ignores_none(self, connected_pair):
        t1, t2 = connected_pair
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t2._in_queue.put(None)
        import time
        time.sleep(0.1)
        assert len(received) == 0

    def test_handler_exception_does_not_crash(self, connected_pair):
        t1, t2 = connected_pair
        t2.start()

        def bad_handler(msg):
            raise RuntimeError("boom")

        t2.set_message_handler(bad_handler)
        t2._in_queue.put("trigger")

    def test_deliver_adds_to_in_queue(self, transport):
        import asyncio
        transport.start()
        asyncio.run(transport.deliver("test message"))
        # After deliver, the in_queue should have the message
        msg = transport._in_queue.get(timeout=0.1)
        assert msg == "test message"

    def test_set_out_handler_overflow_logged(self, transport):
        """When out_handler raises, warning is logged (no crash)."""
        transport.start()

        def failing_handler(msg):
            raise RuntimeError("out handler failed")

        transport.set_out_handler(failing_handler)
        transport.send("test")  # should not crash


class TestStop:
    def test_stop_joins_reader_thread(self, transport):
        transport.start()
        transport.stop()
        # After stop, reader thread should be done
        if transport._reader_thread:
            assert not transport._reader_thread.is_alive()

    def test_multiple_stop_safe(self, transport):
        transport.start()
        transport.stop()
        transport.stop()  # should not raise

    def test_stop_sentinel_pushed(self, transport):
        transport.start()
        transport.stop()
        import time
        time.sleep(0.1)
        # The sentinel should have been put into the queue
        assert transport._in_queue.qsize() > 0

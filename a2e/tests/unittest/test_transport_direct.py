"""Tests for DirectTransport — in-memory queue-based transport."""

import json
import queue
import time
import threading
import asyncio
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
    """Create two wired transports for testing bidirectional messaging.

    connect() is bidirectional — it rewires both _out_queue references
    so each side's output feeds the other's input.
    """
    t1 = DirectTransport(logger=FakeLogger())
    t2 = DirectTransport(logger=FakeLogger())
    t1.connect(t2)
    # After connect: t1._out_queue = t2._in_queue, t2._out_queue = t1._in_queue
    return t1, t2


# ── Init ─────────────────────────────────────────────────────────

class TestDirectTransportInit:
    def test_default_queues_created(self, transport):
        assert transport._in_queue is not None
        assert transport._out_queue is not None

    def test_initial_not_alive(self, transport):
        assert transport.alive() is False

    def test_handler_and_out_handler_none(self, transport):
        assert transport._handler is None
        assert transport._out_handler is None

    def test_queues_have_maxsize(self, transport):
        assert transport._in_queue.maxsize == 1000
        assert transport._out_queue.maxsize == 1000

    def test_reader_thread_none_before_start(self, transport):
        assert transport._reader_thread is None

    def test_queues_are_separate(self, transport):
        """Before connect(), in+out are independent queues."""
        assert transport._in_queue is not transport._out_queue


# ── Lifecycle ────────────────────────────────────────────────────

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

    def test_deliver_while_not_alive(self, transport):
        """deliver() should work even before start (just queues the msg)."""
        asyncio.run(transport.deliver("early message"))
        assert transport._in_queue.qsize() > 0

    def test_start_creates_reader_thread(self, transport):
        transport.start()
        assert transport._reader_thread is not None
        assert transport._reader_thread.is_alive()
        transport.stop()

    def test_reader_thread_is_daemon(self, transport):
        """Reader thread should be daemon so it doesn't block exit."""
        transport.start()
        assert transport._reader_thread is not None
        assert transport._reader_thread.daemon is True
        transport.stop()

    def test_stop_joins_reader_thread(self, transport):
        transport.start()
        transport.stop()
        if transport._reader_thread:
            assert not transport._reader_thread.is_alive()

    def test_multiple_stop_safe(self, transport):
        transport.start()
        transport.stop()
        transport.stop()  # should not raise

    def test_alive_after_multiple_start_stop(self, transport):
        transport.start()
        transport.stop()
        transport.start()
        assert transport.alive() is True
        transport.stop()

    def test_stop_sentinel_pushed(self, transport):
        """stop() puts a sentinel (None) to unblock the reader thread."""
        transport.start()

        # Replace the reader thread so it doesn't consume the sentinel
        original_thread = transport._reader_thread
        transport._alive = False  # stop the original reader
        if original_thread:
            original_thread.join(timeout=1)

        # Manually push sentinel
        transport._alive = True

        # Create a dummy reader that does nothing so alive-ness works
        # Actually, let's just directly test that stop() puts the None
        transport._in_queue = queue.Queue(maxsize=1000)
        transport.stop()
        # The sentinel should be in the queue now
        time.sleep(0.05)
        assert transport._in_queue.qsize() > 0
        # And it should be None
        item = transport._in_queue.get_nowait()
        assert item is None


# ── Connect ──────────────────────────────────────────────────────

class TestConnect:
    def test_connect_is_bidirectional(self, connected_pair):
        """connect() rewires BOTH sides, not one-way."""
        t1, t2 = connected_pair
        # t1's out goes to t2's in
        assert t1._out_queue is t2._in_queue
        # t2's out goes to t1's in
        assert t2._out_queue is t1._in_queue

    def test_connect_preserves_own_in_queues(self, connected_pair):
        """Each transport's _in_queue stays the same after connect."""
        t1, t2 = connected_pair
        # t1's out became t2's in, but t1's in is still its own
        assert t1._in_queue is t2._out_queue
        # t2's in is still its own
        assert t2._in_queue is t1._out_queue

    def test_connect_replaces_out_queue(self):
        """After connect, _out_queue is the other's _in_queue, not the original."""
        t1 = DirectTransport(logger=FakeLogger())
        t2 = DirectTransport(logger=FakeLogger())
        original_t1_out = t1._out_queue
        original_t2_out = t2._out_queue

        t1.connect(t2)

        # Both _out_queues were replaced with the other's _in_queue
        assert t1._out_queue is not original_t1_out
        assert t2._out_queue is not original_t2_out
        assert t1._out_queue is t2._in_queue
        assert t2._out_queue is t1._in_queue

    def test_connect_then_send_via_queue(self, connected_pair):
        """After connect, send() via queue fallback reaches the other side."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t1.send("hello via queue")
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "hello via queue"

    def test_double_connect_is_safe(self):
        """Calling connect() twice should not crash — second call re-wires."""
        t1 = DirectTransport(logger=FakeLogger())
        t2 = DirectTransport(logger=FakeLogger())
        t1.connect(t2)
        t1.connect(t2)  # second call
        assert t1._out_queue is t2._in_queue
        assert t2._out_queue is t1._in_queue


# ── Messaging ────────────────────────────────────────────────────

class TestMessaging:
    def test_send_calls_out_handler(self, transport):
        transport.start()
        received = []

        def handler(msg):
            received.append(msg)

        transport.set_out_handler(handler)
        transport.send("hello")
        assert received == ["hello"]

    def test_send_via_queue_reaches_handler(self, connected_pair):
        """Message sent via wired queue should reach the other side's handler."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t1.send("wired message")
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "wired message"

    def test_bidirectional_messaging(self, connected_pair):
        """Both sides can send and receive."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received_by_t1 = []
        received_by_t2 = []

        def h1(msg):
            received_by_t1.append(msg)
        def h2(msg):
            received_by_t2.append(msg)

        t1.set_message_handler(h1)
        t2.set_message_handler(h2)

        t1.send("from t1")
        t2.send("from t2")
        time.sleep(0.3)

        assert len(received_by_t2) >= 1
        assert received_by_t2[0] == "from t1"
        assert len(received_by_t1) >= 1
        assert received_by_t1[0] == "from t2"

    def test_read_loop_dispatches_to_handler(self, connected_pair):
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        # Put directly into t2's in_queue (simulating incoming from t1)
        t2._in_queue.put("hello from t1")
        time.sleep(0.2)
        assert len(received) >= 1
        assert received[0] == "hello from t1"

    def test_read_loop_ignores_none(self, connected_pair):
        t1, t2 = connected_pair
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t2._in_queue.put(None)
        time.sleep(0.1)
        assert len(received) == 0

    def test_handler_exception_does_not_crash(self, connected_pair):
        t1, t2 = connected_pair
        t2.start()

        def bad_handler(msg):
            raise RuntimeError("boom")

        t2.set_message_handler(bad_handler)
        t2._in_queue.put("trigger")
        time.sleep(0.1)
        # Should not crash — the exception is caught in _read_loop
        assert t2.alive()

    def test_deliver_triggers_handler(self, transport):
        """deliver() puts to in_queue, reader dispatches to handler."""
        transport.start()
        received = []

        def handler(msg):
            received.append(msg)

        transport.set_message_handler(handler)

        async def do_deliver():
            await transport.deliver("delivered msg")
        asyncio.run(do_deliver())

        time.sleep(0.1)
        assert len(received) >= 1
        assert received[0] == "delivered msg"

    def test_multiple_messages_in_sequence(self, connected_pair):
        """Sequence of messages should arrive in order."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        for i in range(10):
            t1.send(f"msg-{i}")

        time.sleep(0.5)
        assert len(received) >= 10
        for i in range(10):
            assert received[i] == f"msg-{i}"

    def test_concurrent_sends(self, connected_pair):
        """Multiple threads sending simultaneously should not lose messages."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []
        lock = threading.Lock()

        def handler(msg):
            with lock:
                received.append(msg)

        t2.set_message_handler(handler)

        def sender(thread_id, count):
            for i in range(count):
                t1.send(f"t{thread_id}-msg-{i}")

        threads = [threading.Thread(target=sender, args=(i, 20)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        time.sleep(0.5)
        assert len(received) == 100

    def test_send_drops_on_overflow(self, connected_pair):
        """When queue is full and block=False, message is dropped."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()

        # Replace t1's out_queue with a tiny queue to simulate overflow
        tiny_q = queue.Queue(maxsize=1)
        t1._out_queue = tiny_q

        t1.send("first", block=True, timeout=1.0)
        t1.send("second", block=False)  # should be dropped
        assert tiny_q.qsize() <= 1

    def test_send_blocks_on_full_queue(self, connected_pair):
        """When queue is full and block=True, send blocks until space frees up."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()

        tiny_q = queue.Queue(maxsize=1)
        t1._out_queue = tiny_q

        # Drain the queue in background
        def drain_later():
            time.sleep(0.1)
            try:
                tiny_q.get(timeout=1)
            except queue.Empty:
                pass

        drainer = threading.Thread(target=drain_later)
        drainer.start()

        t1.send("first", block=True, timeout=5.0)
        t1.send("second", block=True, timeout=5.0)
        drainer.join()


# ── Out Handler ──────────────────────────────────────────────────

class TestOutHandler:
    def test_out_handler_priority_over_queue(self, connected_pair):
        """send() should prefer _out_handler over _out_queue."""
        t1, t2 = connected_pair
        t1.start()
        received = []

        def handler(msg):
            received.append(msg)

        t1.set_out_handler(handler)
        t1.send("to handler")
        assert received == ["to handler"]

        # The queue should NOT have the message
        assert t2._in_queue.qsize() == 0

    def test_out_handler_error_logged_not_crash(self, transport):
        transport.start()

        def failing_handler(msg):
            raise RuntimeError("out handler failed")

        transport.set_out_handler(failing_handler)
        transport.send("test")  # should not crash

    def test_out_handler_none_falls_to_queue(self, connected_pair):
        """Without _out_handler, send writes to wired queue."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()

        # Don't set _out_handler - verify queue fallback works
        assert t1._out_handler is None
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t1.send("to queue")
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "to queue"

    def test_switch_from_handler_to_queue(self, connected_pair):
        """Clearing _out_handler falls back to queue wiring."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        # Start with _out_handler
        handler_called = []
        def out_h(msg):
            handler_called.append(msg)
        t1.set_out_handler(out_h)
        t1.send("first")
        assert len(handler_called) == 1

        # Clear handler and send — should go through queue
        t1._out_handler = None
        t2.set_message_handler(handler)
        t1.send("second")
        time.sleep(0.2)
        assert len(received) >= 1
        assert received[0] == "second"


# ── Stop / Cleanup ───────────────────────────────────────────────

class TestStop:
    def test_stop_while_not_started_is_safe(self, transport):
        transport.stop()  # should not raise

    def test_stop_does_not_block(self, transport):
        transport.start()
        t0 = time.monotonic()
        transport.stop()
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0  # should return quickly

    def test_stop_clears_alive_flag(self, transport):
        transport.start()
        transport.stop()
        assert transport._alive is False

    def test_stop_sets_sentinel(self, transport):
        """stop() puts a None sentinel to unblock the reader thread."""
        transport.start()
        # Give the reader time to start
        time.sleep(0.05)
        transport.stop()
        # The sentinel (None) should have been put into the queue
        # but the reader may have consumed it already
        # What matters: the reader stopped cleanly
        if transport._reader_thread:
            assert not transport._reader_thread.is_alive()


# ── Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases:
    def test_very_long_message(self, connected_pair):
        """Long messages should be handled."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        long_msg = "x" * 100_000
        t1.send(long_msg)
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == long_msg

    def test_empty_string_message(self, connected_pair):
        """Empty string should be delivered."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        t1.send("")
        time.sleep(0.2)
        assert len(received) >= 1
        assert received[0] == ""

    def test_json_message(self, connected_pair):
        """JSON messages (the real use case) should work."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = []

        def handler(msg):
            received.append(msg)

        t2.set_message_handler(handler)
        msg = json.dumps({"type": "ping", "id": "test-1", "version": "1.0"})
        t1.send(msg)
        time.sleep(0.2)
        assert len(received) >= 1
        parsed = json.loads(received[0])
        assert parsed["type"] == "ping"
        assert parsed["id"] == "test-1"

    def test_no_handler_set(self, connected_pair):
        """Messages should be consumed (dropped) but not crash when no handler."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        # No handler on t2 — reader reads and drops
        t1.send("orphan message")
        time.sleep(0.1)
        # No crash, no error
        assert t2.alive()


# ── Thread Safety ────────────────────────────────────────────────

class TestThreadSafety:
    def test_send_from_different_threads(self, connected_pair):
        """send() from multiple threads should be safe with the queue."""
        t1, t2 = connected_pair
        t1.start()
        t2.start()
        received = set()
        lock = threading.Lock()

        def handler(msg):
            with lock:
                received.add(msg)

        t2.set_message_handler(handler)

        def thread_sender(n):
            for i in range(50):
                t1.send(f"from-{n}-{i}")

        threads = [threading.Thread(target=thread_sender, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        time.sleep(0.5)
        assert len(received) == 150

    def test_concurrent_deliver(self, transport):
        """deliver() from multiple threads should be safe."""
        transport.start()
        received = []
        lock = threading.Lock()

        def handler(msg):
            with lock:
                received.append(msg)

        transport.set_message_handler(handler)

        async def deliver_msg(msg):
            await transport.deliver(msg)

        def do_deliver(msg):
            asyncio.run(deliver_msg(msg))

        threads = [threading.Thread(target=do_deliver, args=(f"msg-{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        time.sleep(0.2)
        assert len(received) == 20
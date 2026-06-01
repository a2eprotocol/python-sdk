"""Tests for SubprocessTransport — stdin/stdout subprocess communication.

Uses a short Python echo script as the test subprocess. The script reads
line-delimited JSON from stdin and writes it back to stdout.
"""

import json
import os
import sys
import time
import signal
import threading
import pytest

from a2e.core.transports.subprocess import SubprocessTransport


# ── Helpers ──────────────────────────────────────────────────────

ECHO_SCRIPT = """
import sys
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
"""


def echo_cmd():
    """Return command list for an echo subprocess."""
    return [sys.executable, "-c", ECHO_SCRIPT]


class FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def transport():
    t = SubprocessTransport(
        command=echo_cmd(),
        logger=FakeLogger(),
    )
    t.start()
    yield t
    t.stop()


@pytest.fixture
def transport_with_handler():
    """SubprocessTransport with a message handler wired up."""
    t = SubprocessTransport(
        command=echo_cmd(),
        logger=FakeLogger(),
    )
    received = []

    def handler(msg):
        received.append(msg)

    t.set_message_handler(handler)
    t.start()
    return t, received


# ── Basic Lifecycle ──────────────────────────────────────────────

class TestLifecycle:
    def test_start_marks_alive(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        assert t.alive() is False
        t.start()
        assert t.alive() is True
        t.stop()

    def test_double_start_raises(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        with pytest.raises(RuntimeError, match="already started"):
            t.start()
        t.stop()

    def test_stop_marks_not_alive(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        t.stop()
        assert t.alive() is False

    def test_stop_while_not_started_safe(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.stop()  # should not raise

    def test_multiple_stop_safe(self, transport):
        transport.stop()
        transport.stop()  # should not raise

    def test_alive_during_running(self, transport):
        assert transport.alive() is True

    def test_alive_after_process_exits(self):
        """After process exits, alive() should return False."""
        t = SubprocessTransport(
            command=echo_cmd(),
            logger=FakeLogger(),
        )
        t.start()
        assert t.alive() is True
        # Terminate the subprocess
        assert t._proc is not None
        t._proc.terminate()
        t._proc.wait(timeout=5)
        t._reader_thread.join(timeout=2)
        assert t.alive() is False
        t.stop()

    def test_start_sets_reader_thread(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        assert t._reader_thread is not None
        assert t._reader_thread.is_alive()
        t.stop()

    def test_stop_kills_process(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        pid = t._proc.pid
        t.stop()
        # process should no longer be running
        with pytest.raises(OSError):
            os.kill(pid, 0)  # kill with 0 just checks if process exists


# ── Send / Receive ──────────────────────────────────────────────

class TestSendReceive:
    def test_send_and_receive(self, transport_with_handler):
        """Basic send -> echo -> receive cycle."""
        transport, received = transport_with_handler
        transport.send("hello subprocess")
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "hello subprocess"

    def test_multiple_messages_ordered(self, transport_with_handler):
        """Messages should be echoed back in order."""
        transport, received = transport_with_handler
        for i in range(10):
            transport.send(f"msg-{i}")

        time.sleep(0.5)
        assert len(received) >= 10
        for i in range(10):
            assert received[i] == f"msg-{i}"

    def test_json_message_roundtrip(self, transport_with_handler):
        """JSON messages (the real use case) round-trip correctly."""
        transport, received = transport_with_handler
        msg = json.dumps({"type": "ping", "id": "test-1", "version": "1.0"})
        transport.send(msg)
        time.sleep(0.3)
        assert len(received) >= 1
        parsed = json.loads(received[0])
        assert parsed["type"] == "ping"
        assert parsed["id"] == "test-1"
        assert parsed["version"] == "1.0"

    def test_empty_string(self, transport_with_handler):
        """Empty strings are a no-op: written as newline, echoed back as
        empty line, which the transport reader correctly skips
        (NDJSON protocol: empty lines have no meaning)."""
        transport, received = transport_with_handler
        transport.send("")
        time.sleep(0.2)
        # Empty string should not produce a callback (it's filtered by the reader)
        assert len(received) == 0

    def test_very_long_message(self, transport_with_handler):
        """Long messages should be handled."""
        transport, received = transport_with_handler
        long_msg = "x" * 100_000
        transport.send(long_msg)
        time.sleep(0.5)
        assert len(received) >= 1
        assert received[0] == long_msg

    def test_unicode_message(self, transport_with_handler):
        """Unicode strings should be handled."""
        transport, received = transport_with_handler
        msg = "héllo wörld 🔥 🎉"
        transport.send(msg)
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == msg

    def test_deliver_triggers_handler(self, transport_with_handler):
        """deliver() should invoke the message handler."""
        transport, received = transport_with_handler
        import asyncio
        asyncio.run(transport.deliver("via deliver"))
        time.sleep(0.1)
        assert len(received) >= 1
        assert received[0] == "via deliver"


# ── Handler-less mode ───────────────────────────────────────────

class TestHandlerLess:
    def test_no_handler_still_reads_stdout(self):
        """Without handler, the reader thread reads but discards."""
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        t.send("no handler")
        time.sleep(0.2)
        # No crash — reader just discards
        t.stop()

    def test_handler_can_be_set_after_start(self):
        """Handler should work even if set after start()."""
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()
        received = []

        def handler(msg):
            received.append(msg)

        t.set_message_handler(handler)
        t.send("delayed handler")
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "delayed handler"
        t.stop()


# ── Error handling ──────────────────────────────────────────────

class TestErrorHandling:
    def test_send_after_stop_raises(self, transport):
        transport.stop()
        with pytest.raises(RuntimeError, match="not started|not alive"):
            transport.send("after stop")

    def test_send_before_start_raises(self):
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        with pytest.raises(RuntimeError, match="not started|not alive"):
            t.send("before start")

    def test_send_to_dead_process(self):
        """Sending to a process that has exited should raise."""
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        t.start()

        # Kill the subprocess
        assert t._proc is not None
        t._proc.terminate()
        t._proc.wait(timeout=5)

        time.sleep(0.2)

        # send should now raise (BrokenPipeError -> RuntimeError)
        with pytest.raises(RuntimeError, match="process exited|not alive|stdin closed"):
            t.send("to dead process")

        t.stop()

    def test_handler_exception_does_not_crash(self):
        """Exception in message handler should be caught, not crash the reader."""
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())

        def bad_handler(msg):
            raise RuntimeError("boom")

        t.set_message_handler(bad_handler)
        t.start()
        t.send("trigger")
        time.sleep(0.3)
        # Reader thread should still be alive
        assert t.alive() is True
        t.stop()


# ── Concurrent sends ──────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_sends(self):
        """Multiple threads sending should not lose or corrupt messages."""
        t = SubprocessTransport(command=echo_cmd(), logger=FakeLogger())
        received = []
        lock = threading.Lock()

        def handler(msg):
            with lock:
                received.append(msg)

        t.set_message_handler(handler)
        t.start()

        def thread_sender(n, count):
            for i in range(count):
                t.send(f"t{n}-msg-{i}")

        threads = [threading.Thread(target=thread_sender, args=(i, 10)) for i in range(5)]
        for thr in threads:
            thr.start()
        for thr in threads:
            thr.join(timeout=10)

        time.sleep(0.5)
        assert len(received) == 50
        t.stop()


# ── Process management ────────────────────────────────────────

class TestProcessManagement:
    def test_custom_env(self):
        """Custom env should be passed to the subprocess."""
        env = {"A2E_TEST_VAR": "hello_test"}
        t = SubprocessTransport(
            command=[sys.executable, "-c", """
import os, sys
val = os.environ.get("A2E_TEST_VAR", "NOT_SET")
sys.stdout.write(val + "\\n")
sys.stdout.flush()
sys.stdin.readline()  # keep alive
"""],
            logger=FakeLogger(),
            env=env,
        )
        received = []

        def handler(msg):
            received.append(msg)

        t.set_message_handler(handler)
        t.start()
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0] == "hello_test"
        t.stop()

    def test_custom_cwd(self):
        """Custom working directory should be used."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            t = SubprocessTransport(
                command=[sys.executable, "-c", """
import os, sys
sys.stdout.write(os.getcwd() + "\\n")
sys.stdout.flush()
sys.stdin.readline()
"""],
                logger=FakeLogger(),
                cwd=tmpdir,
            )
            received = []

            def handler(msg):
                received.append(msg)

            t.set_message_handler(handler)
            t.start()
            time.sleep(0.3)
            assert len(received) >= 1
            assert os.path.samefile(received[0], tmpdir)
            t.stop()

    def test_non_existent_command(self):
        """Starting with a non-existent command should raise."""
        t = SubprocessTransport(
            command=["/nonexistent/binary"],
            logger=FakeLogger(),
        )
        with pytest.raises(FileNotFoundError):
            t.start()
        t.stop()


# ── First-message / startup-output tests ────────────────────────

class TestStartupOutput:
    def test_capture_startup_message(self):
        """Messages emitted by the subprocess before any send should be captured."""
        t = SubprocessTransport(
            command=[sys.executable, "-c", """
import sys
sys.stdout.write("READY\\n")
sys.stdout.flush()
import sys
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
"""],
            logger=FakeLogger(),
        )
        received = []

        def handler(msg):
            received.append(msg)

        t.set_message_handler(handler)
        t.start()
        time.sleep(0.3)

        assert len(received) >= 1
        assert received[0] == "READY"

        # Regular messaging should still work
        t.send("hello")
        time.sleep(0.2)
        assert len(received) >= 2
        assert received[1] == "hello"
        t.stop()


# ── Stop timeout / forced kill ─────────────────────────────────

class TestStopEdgeCases:
    def test_stop_handles_refusing_process(self):
        """If process won't exit, stop should force kill."""
        t = SubprocessTransport(
            command=[sys.executable, "-c", """
import signal, sys
# Ignore SIGTERM to test force-kill fallback
signal.signal(signal.SIGTERM, signal.SIG_IGN)
sys.stdout.write("stubborn\\n")
sys.stdout.flush()
while True:
    try:
        sys.stdin.readline()
    except:
        break
"""],
            logger=FakeLogger(),
            start_timeout=2.0,
        )
        received = []

        def handler(msg):
            received.append(msg)

        t.set_message_handler(handler)
        t.start()
        time.sleep(0.2)
        assert len(received) >= 1
        assert received[0] == "stubborn"

        # Stop should force-kill
        t.stop()
        assert t.alive() is False

    def test_stop_initial_close_timeout(self):
        """Stop handles the case where closing stdin alone is not enough."""
        # Fast stop test: process that exits on stdin close
        t = SubprocessTransport(
            command=[sys.executable, "-c", """
import sys
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
"""],
            logger=FakeLogger(),
        )
        t.start()
        t.send("bye")
        t0 = time.monotonic()
        t.stop()
        elapsed = time.monotonic() - t0
        # Should be fast because the echo process exits cleanly
        assert elapsed < 3.0
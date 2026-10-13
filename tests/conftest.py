"""Shared fixtures: an isolated config dir and a fake printer that keeps bytes.

`HOME` / `APPDATA` are redirected before any service module is imported —
`config.get_config_path()` reads them at call time but `app._setup_logging()`
runs at import and would otherwise drop a log file in the real config dir.
"""
import os
import socket
import tempfile
import threading
import time

import pytest

_ISOLATED_HOME = tempfile.mkdtemp(prefix="relims-print-tests-")
os.environ["HOME"] = _ISOLATED_HOME
os.environ["APPDATA"] = _ISOLATED_HOME

import config  # noqa: E402  (must follow the env redirect above)


class FakePrinter:
    """A socket server standing in for a label printer on port 9100.

    Captures each connection's bytes separately, so a test can assert not just
    what was sent but how it was framed — one job per connection is what keeps
    another application from interleaving a print between a label and the
    restore that follows it.
    """

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self.connections = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                chunks = []
                while True:
                    try:
                        data = conn.recv(4096)
                    except OSError:
                        break
                    if not data:
                        break
                    chunks.append(data)
                self.connections.append(b"".join(chunks).decode("utf-8"))

    def wait(self, connections=1, timeout=2.0):
        """Block until `connections` jobs have been received in full.

        The HTTP response returns as soon as the service closes its socket,
        which is before this thread has seen EOF and recorded the bytes.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.connections) >= connections:
                return
            time.sleep(0.005)
        raise AssertionError(
            f"expected {connections} job(s), got {len(self.connections)}: {self.connections!r}"
        )

    def settle(self, seconds=0.15):
        """Give any job that should NOT have been sent time to show up."""
        time.sleep(seconds)
        return "".join(self.connections)

    @property
    def received(self):
        """Everything sent, joined — for assertions that ignore framing."""
        self.wait()
        return "".join(self.connections)

    def close(self):
        self._sock.close()


@pytest.fixture
def fake_printer():
    printer = FakePrinter()
    yield printer
    printer.close()


@pytest.fixture
def configure(fake_printer):
    """Write a config pointing at the fake printer. Returns a setter."""
    def _configure(**overrides):
        settings = {
            "backend": "network",
            "printer_host": "127.0.0.1",
            "printer_port": fake_printer.port,
            "timeout": 5,
        }
        settings.update(overrides)
        config.save_config(settings)
        return settings

    _configure()
    return _configure


@pytest.fixture(autouse=True)
def clean_config():
    """Every test starts from the packaged defaults."""
    path = config.get_config_path()
    if path.exists():
        path.unlink()
    yield
    if path.exists():
        path.unlink()


# Both service modules are exercised: they are near-duplicates that have drifted
# before (`raw` was honoured only on Linux until v2.0.13), and the Windows one
# runs fine here as long as the backend is "network".
def _client(module_name):
    module = __import__(module_name)
    module.app.config["TESTING"] = True
    return module.app.test_client()


@pytest.fixture(params=["app", "app_linux"])
def client(request):
    """A Flask test client for each of the two service modules in turn."""
    return _client(request.param)

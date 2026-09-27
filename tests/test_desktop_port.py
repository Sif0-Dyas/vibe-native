"""The desktop shell adopts only a backend that knows THIS launch's token.

A server on the shell's port that answers 403 to our token is someone else's (a
stale dev server, say). The shell used to take any non-5xx answer as "our backend
is up" and navigate into it; now it notes who holds the port and moves to a free
one. Stub HTTP servers stand in for "ours" and "foreign"; the real backend start
is replaced, so nothing here launches the app.
"""

import http.server
import importlib.machinery
import importlib.util
import os
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

SHELL = Path(__file__).resolve().parent.parent / "desktop" / "genre_app.pyw"
TOKEN = "this-launch-token"  # nosec B105  # a fake token for the test


@pytest.fixture()
def shell(monkeypatch, tmp_path):
    """A fresh copy of genre_app.pyw, pointed at a temp project dir."""
    monkeypatch.setenv("GENRE_WIN_PROJECT", str(tmp_path))
    monkeypatch.delenv("GENRE_PORT", raising=False)
    monkeypatch.setenv("GENRE_TOKEN", TOKEN)
    loader = importlib.machinery.SourceFileLoader("genre_app_under_test", str(SHELL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    started = []
    monkeypatch.setattr(mod, "_start_inprocess", lambda: started.append(mod.PORT))
    monkeypatch.setattr(mod, "use_single_process", lambda: True)
    mod.started = started
    return mod


def _stub(status_for):
    """A loopback HTTP server answering status_for(token_sent) to every GET."""
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            k = parse_qs(urlsplit(self.path).query).get("k", [""])[0]
            seen.append(self.path)
            self.send_response(status_for(k))
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _point_at(shell, port):
    shell.PORT, shell.BASE_URL = port, f"http://127.0.0.1:{port}"


def test_a_server_that_403s_our_token_is_not_adopted(shell):
    srv, seen = _stub(lambda k: 403)
    try:
        port = srv.server_address[1]
        _point_at(shell, port)
        assert shell._probe() == "foreign"
        assert shell.backend_up() is False
        ok, err = shell._ensure_backend_started()
    finally:
        srv.shutdown()
        srv.server_close()
    assert (ok, err) == (True, None)
    assert shell.PORT != port and shell.BASE_URL == f"http://127.0.0.1:{shell.PORT}"
    assert shell.started == [shell.PORT]  # our own backend, on the NEW port
    assert f"port {port} is held by another server" in shell._PORT_NOTE
    assert f"k={TOKEN}" in seen[0]  # it asked with this launch's token
    if sys.platform == "win32":  # netstat names the holder: this test process
        assert f"PID {os.getpid()}" in shell._PORT_NOTE


def test_our_own_backend_is_reused(shell):
    srv, _ = _stub(lambda k: 200 if k == TOKEN else 403)
    try:
        port = srv.server_address[1]
        _point_at(shell, port)
        assert shell._probe() == "ours" and shell.backend_up() is True
        assert shell._ensure_backend_started() == (True, None)
    finally:
        srv.shutdown()
        srv.server_close()
    assert shell.PORT == port and shell.started == [] and shell._PORT_NOTE is None


def test_nothing_listening_means_start_on_that_port(shell):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    _point_at(shell, port)
    assert shell._probe() == "down"
    assert shell._ensure_backend_started() == (True, None)
    assert shell.started == [port] and shell._PORT_NOTE is None

"""A server refuses a port something else already holds, instead of sharing it.

On Windows a stale dev server and a fresh one both listened on 5005 and the stale
one answered (see vibenative/preflight.py). Both holders are covered: a plain
listener, and one with SO_REUSEADDR set -- how the dev server binds.
"""

import importlib
import socket

import pytest

from vibenative import preflight


def _holder(reuse):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("reuse", [False, True], ids=["plain-holder", "reuseaddr-holder"])
def test_a_held_port_exits_with_one_line(reuse):
    with _holder(reuse) as h:
        port = h.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            preflight.ensure_port_free("127.0.0.1", port)
    assert str(exc.value) == f"port {port} is already in use — is another Vibe server running?"


def test_a_free_port_passes_and_stays_free():
    port = _free_port()
    preflight.ensure_port_free("127.0.0.1", port)
    preflight.ensure_port_free("127.0.0.1", port)  # the check released it again


@pytest.mark.parametrize("reuse", [False, True], ids=["plain-holder", "reuseaddr-holder"])
def test_main_refuses_before_touching_the_app(monkeypatch, capsys, reuse):
    entry = importlib.import_module("vibenative.__main__")

    def must_not_run():
        raise AssertionError("create_app ran although the port was taken")

    monkeypatch.setattr(entry, "create_app", must_not_run)
    with _holder(reuse) as h:
        port = h.getsockname()[1]
        monkeypatch.setenv("GENRE_PORT", str(port))
        with pytest.raises(SystemExit) as exc:
            entry.main()
    assert str(exc.value) == f"port {port} is already in use — is another Vibe server running?"
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""  # "and nothing else": no URL, no log lines

"""Refuse to start a server on a port something else already holds.

On Windows two processes can both listen on the same port: the dev server's
socket sets SO_REUSEADDR, which there means "let me share it". A stale server from
two days earlier sat on 5005 next to a fresh one, and requests went to the stale
one -- old page, new JS, 500s everywhere. Nothing said a word.

So before serving, bind a throwaway socket to host:port EXCLUSIVELY -- Windows'
SO_EXCLUSIVEADDRUSE, and elsewhere a plain bind with SO_REUSEADDR left off -- and
close it again. If that bind fails, the port is taken: exit with one line.

Used by ``python -m vibenative`` and ``wsgi.py``. (Not suitable under a server
that binds its listening socket BEFORE importing the app, such as gunicorn's
default: there the port is held by the server itself by the time this runs.)
"""

import socket

IN_USE = "port {port} is already in use — is another Vibe server running?"


def ensure_port_free(host: str, port: int) -> None:
    """Exit (non-zero, one line, no traceback) if host:port can't be bound exclusively."""
    try:
        family, _, _, _, addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    except socket.gaierror:
        family, addr = socket.AF_INET, (host, port)
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(addr)
    except OSError:
        raise SystemExit(IN_USE.format(port=port)) from None
    finally:
        s.close()

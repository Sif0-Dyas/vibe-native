"""Serving the app: waitress, sized for batches, with a request log line.

The one place the WSGI server is created -- ``python -m vibenative`` and the
desktop shell's in-process backend both come through here. The port pre-flight
(preflight.py) is the caller's job and must run first: ``__main__`` does it before
touching the app, the shell before starting its server thread.
"""

import logging

from flask import request

# The most analysis workers one /batch may use (the route clamps to this).
MAX_BATCH_WORKERS = 6

# waitress request threads. A running /batch holds one for as long as it streams
# (its analysis runs on the batch's own worker pool, not on these), so allow that
# many streams, plus a few for the UI's own parallel requests -- page, map,
# library, waveforms, audio range requests.
UI_THREADS = 4
THREADS = MAX_BATCH_WORKERS + UI_THREADS

_req_log = logging.getLogger("vibenative.requests")


def create_server(app, host: str, port: int):
    """A waitress server for ``app`` (not yet running): ``.run()`` / ``.close()``."""
    from waitress import create_server as _create

    return _create(app, host=host, port=port, threads=THREADS, ident="Vibenative")


def serve(app, host: str, port: int) -> None:
    """Serve ``app`` until the process ends. Run the port pre-flight first."""
    create_server(app, host, port).run()


def log_requests(app) -> None:
    """One INFO line per request: method, path, status.

    waitress logs no requests of its own, and the dev server's per-request lines
    were how problems got debugged, so this puts them back. The path only, never
    the query string: the first navigation carries the auth token as ``?k=``,
    which the old werkzeug lines wrote straight into the log."""

    @app.after_request
    def _log(resp):
        _req_log.info("%s %s %s", request.method, request.path, resp.status_code)
        return resp

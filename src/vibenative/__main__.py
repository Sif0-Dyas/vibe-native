"""Development entry point:  python -m vibenative

Serves real native (ONNX) analysis on http://localhost:5005. Set FAKE_ANALYZER=1
for instant fake results with no models loaded. For production use a WSGI
server against ``wsgi:app`` instead of this dev server.
"""

import logging
import os

from . import auth, create_app, preflight, serve

log = logging.getLogger("vibenative")


def _check_ffmpeg():
    """Warn (don't crash) if ffmpeg/ffprobe aren't locatable in real mode. The
    server still boots -- cached-library browsing works without them -- but new
    analysis needs ffmpeg to decode audio, so surface a helpful, actionable hint."""
    from .decode import find_tool

    missing = [t for t in ("ffmpeg", "ffprobe") if not find_tool(t)]
    if missing:
        log.warning(
            "%s not found on PATH or the WinGet Links dir -- audio decode will fail. "
            "Install it with:  winget install Gyan.FFmpeg   (then reopen the terminal). "
            "Cached tracks still load; only NEW analysis needs ffmpeg.",
            " + ".join(missing),
        )


def main():
    host = os.environ.get("GENRE_HOST", "127.0.0.1")
    port = int(os.environ.get("GENRE_PORT", "5005"))
    # First, before the app (and its database) is touched: refuse a port another
    # server already holds, instead of silently sharing it (see preflight.py).
    preflight.ensure_port_free(host, port)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app()
    if os.environ.get("FAKE_ANALYZER") == "1":
        log.info("FAKE_ANALYZER=1 -- serving fake results (GUI test mode, no models).")
    else:
        _check_ffmpeg()
    # Every request needs the token (auth.py). Print the URL that carries it on
    # stdout, on its own line, so it can be copied straight into a browser; the
    # first page load turns it into a cookie. Set GENRE_TOKEN to pin it.
    print(f"\nOpen Vibenative at:\n\n    {auth.launch_url(app, host, port)}\n", flush=True)
    serve.serve(app, host, port)  # waitress; the pre-flight ran at the top


if __name__ == "__main__":
    main()

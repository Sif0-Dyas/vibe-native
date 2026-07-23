"""Development entry point:  python -m vibenative

Serves real native (ONNX) analysis on http://localhost:5005. Set FAKE_ANALYZER=1
for instant fake results with no models loaded. For production use a WSGI
server against ``wsgi:app`` instead of this dev server.
"""

import logging
import os

from . import create_app

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app()
    if os.environ.get("FAKE_ANALYZER") == "1":
        log.info("FAKE_ANALYZER=1 -- serving fake results (GUI test mode, no models).")
    else:
        _check_ffmpeg()
    host = os.environ.get("GENRE_HOST", "127.0.0.1")
    port = int(os.environ.get("GENRE_PORT", "5005"))
    if os.environ.get("GENRE_TOKEN"):
        log.info("GENRE_TOKEN set -- requiring the per-session token on every request.")
    log.info("Vibenative running -> http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

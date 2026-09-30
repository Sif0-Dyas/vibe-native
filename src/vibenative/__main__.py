"""Development entry point:  python -m vibenative

Serves native (ONNX) analysis on http://localhost:5005 -- or instant stand-in
results with no models loaded, in the mode settings.py and fake_engine.py
describe. For production use a WSGI server against ``wsgi:app`` instead of this
dev server.
"""

import logging

from . import PRODUCT_NAME, auth, create_app, preflight, serve
from .fake_engine import engines
from .settings import Settings

log = logging.getLogger("vibenative")


def main():
    settings = Settings.from_env()
    host, port = settings.host, settings.port
    # First, before the app (and its database) is touched: refuse a port another
    # server already holds, instead of silently sharing it (see preflight.py).
    preflight.ensure_port_free(host, port)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app(settings)
    engines().startup_check()  # e.g. warn if ffmpeg is missing
    # Every request needs the token (auth.py). Print the URL that carries it on
    # stdout, on its own line, so it can be copied straight into a browser; the
    # first page load turns it into a cookie. Set GENRE_TOKEN to pin it.
    print(f"\nOpen {PRODUCT_NAME} at:\n\n    {auth.launch_url(app, host, port)}\n", flush=True)
    serve.serve(app, host, port)  # waitress; the pre-flight ran at the top


if __name__ == "__main__":
    main()

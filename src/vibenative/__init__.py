"""Vibe Identify — Flask + native ONNX music genre / BPM / key analyzer.

The package is ``vibenative``; the product -- what a user sees in a window
title, a log folder, the installer or a User-Agent -- is ``PRODUCT_NAME``.

The application is assembled by the :func:`create_app` factory so that tests
(and any WSGI server) get a fresh, independently-configured instance.
"""

from flask import Flask

# THE single source of truth for the app/installer version. Surfaced in the UI footer
# (so an installed build is identifiable) and read by the installer build script to
# stamp Setup. Keep pyproject.toml's [project].version in sync with this.
__version__ = "2.1.0"

# The product's name wherever a user sees it. The desktop shell (which must
# start without importing this package) and the installer spell it out too;
# test_one_name pins them to this.
PRODUCT_NAME = "Vibe Identify"

from . import auth, serve  # noqa: E402 -- after __version__ so routes can read it
from .db import init_db  # noqa: E402
from .routes import API_PREFIX, bp, pages  # noqa: E402
from .settings import Settings, use  # noqa: E402

__all__ = ["create_app", "Settings", "PRODUCT_NAME", "__version__"]


def create_app(settings=None):
    """The app, configured by ``settings`` (default: ``Settings.from_env()``).

    Installs them for the whole package (``settings.use``): the modules read
    ``settings.current()`` at call time, never the environment."""
    settings = use(settings if settings is not None else Settings.from_env())
    app = Flask(__name__)  # templates/ and static/ live inside this package
    app.config["SETTINGS"] = settings
    # Guard against a giant upload exhausting memory (configurable).
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024
    init_db()  # create tables if the DB is new
    # Every request -- routes, /static, and unmatched URLs alike -- needs the token
    # and a loopback Host. settings.token (GENRE_TOKEN) if set (the desktop shell
    # sets one per launch), else a fresh one; see auth.py.
    auth.install(app)
    serve.log_requests(app)
    app.register_blueprint(pages)
    app.register_blueprint(bp, url_prefix=API_PREFIX)
    return app

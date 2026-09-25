"""Vibedentify — Flask + native ONNX music genre / BPM / key analyzer.

The application is assembled by the :func:`create_app` factory so that tests
(and any WSGI server) get a fresh, independently-configured instance.
"""

import os

from flask import Flask

# THE single source of truth for the app/installer version. Surfaced in the UI footer
# (so an installed build is identifiable) and read by the installer build script to
# stamp Setup. Keep pyproject.toml's [project].version in sync with this.
__version__ = "2.1.0"

from . import (  # noqa: E402
    auth,
    config,  # noqa: F401 -- imported after __version__ so routes can read it; loads .env early
)
from .db import init_db  # noqa: E402
from .routes import bp  # noqa: E402

__all__ = ["create_app", "__version__"]


def create_app():
    app = Flask(__name__)  # templates/ and static/ live inside this package
    # Guard against a giant upload exhausting memory (configurable).
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "512")) * 1024 * 1024
    init_db()  # create tables if the DB is new
    # Every request -- routes, /static, and unmatched URLs alike -- needs the token
    # and a loopback Host. GENRE_TOKEN if set (the desktop shell sets one per
    # launch), else a fresh one; see auth.py.
    auth.install(app)
    app.register_blueprint(bp)
    return app

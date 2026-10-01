"""The pages: what a browser opens, as opposed to the API the page calls.

The app's page lives here, at the root (with Flask's /static/*), and /label,
the blind-labelling page (routes/labels.py has why it is a page of its own). Every
API route is on ``bp`` (_shared), which create_app mounts under API_PREFIX.
"""

from flask import Blueprint, render_template

pages = Blueprint("pages", __name__)


@pages.get("/")
def index():
    from .. import __version__

    return render_template("index.html", app_version=__version__)


@pages.get("/label")
def label():
    """Blind labelling: a page of its own rather than a mode of the Analyzer,
    because the Analyzer is built around showing the read -- a flag there would
    have to hide it in every place it appears, and miss the next one added."""
    from .. import PRODUCT_NAME, __version__

    return render_template("label.html", app_version=__version__, product=PRODUCT_NAME)

"""The pages: what a browser opens, as opposed to the API the page calls.

Only the app's one page lives here, at the root (with Flask's /static/*). Every
API route is on ``bp`` (_shared), which create_app mounts under API_PREFIX.
"""

from flask import Blueprint, render_template

pages = Blueprint("pages", __name__)


@pages.get("/")
def index():
    from .. import __version__

    return render_template("index.html", app_version=__version__)

"""WSGI entry point for production servers (gunicorn, waitress, uWSGI):

    gunicorn wsgi:app        # Linux/WSL
    waitress-serve wsgi:app  # cross-platform

The Flask dev server (``python -m vibenative``) is fine for local use.
"""

from vibenative import create_app

app = create_app()

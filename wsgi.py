"""WSGI entry point for production servers (gunicorn, waitress, uWSGI):

    gunicorn wsgi:app        # Linux/WSL
    waitress-serve wsgi:app  # cross-platform

The Flask dev server (``python -m vibenative``) is fine for local use.

Every request needs the app's token (see ``vibenative/auth.py``): GENRE_TOKEN if
set, else a fresh one. The URL carrying it is printed below; it assumes the server
binds GENRE_HOST:GENRE_PORT (default 127.0.0.1:5005) -- if yours binds elsewhere,
keep the ``?k=`` part and change the address.
"""

import os

from vibenative import auth, create_app

app = create_app()

print(
    "\nOpen Vibenative at:\n\n    "
    + auth.launch_url(
        app, os.environ.get("GENRE_HOST", "127.0.0.1"), int(os.environ.get("GENRE_PORT", "5005"))
    )
    + "\n",
    flush=True,
)

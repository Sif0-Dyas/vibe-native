"""WSGI entry point for production servers (gunicorn, waitress, uWSGI):

    gunicorn wsgi:app        # Linux/WSL
    waitress-serve wsgi:app  # cross-platform

The Flask dev server (``python -m vibenative``) is fine for local use.

Every request needs the app's token (see ``vibenative/auth.py``): GENRE_TOKEN if
set, else a fresh one. The URL carrying it is printed below; it assumes the server
binds GENRE_HOST:GENRE_PORT (default 127.0.0.1:5005) -- if yours binds elsewhere,
keep the ``?k=`` part and change the address.

Before anything else, GENRE_HOST:GENRE_PORT must be free (vibenative/preflight.py):
a server already on it exits this one with a single line. That suits a server that
imports the app before binding (waitress-serve); one that binds first (gunicorn's
default) holds the port itself by then, so don't use this entry point with it.
"""

import os

from vibenative import auth, create_app, preflight

_HOST = os.environ.get("GENRE_HOST", "127.0.0.1")
_PORT = int(os.environ.get("GENRE_PORT", "5005"))
preflight.ensure_port_free(_HOST, _PORT)

app = create_app()

print(f"\nOpen Vibenative at:\n\n    {auth.launch_url(app, _HOST, _PORT)}\n", flush=True)

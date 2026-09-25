"""Loopback auth: every request needs the per-run token and a loopback Host.

The server only ever listens on loopback, but that alone does not keep other
local processes -- or a web page in the user's browser -- from driving the API.
So every request must

(a) be addressed to a loopback Host, which defeats DNS rebinding (a malicious
    site resolving its own domain to 127.0.0.1 to reach this server from the
    browser), and
(b) carry the secret: ``?k=<token>`` on the first navigation, thereafter an
    httponly cookie the first response sets.

There is no unauthenticated mode. ``create_app`` takes ``GENRE_TOKEN`` if it is
set (the desktop shell sets a fresh one per launch) and otherwise generates one;
``python -m vibenative`` and ``wsgi.py`` print the URL carrying it.

The hooks are app-level, not blueprint-level, so they also cover ``/static/*``
and unmatched URLs. The first request is ``/?k=<token>``, whose response sets
the cookie before the page asks for any static file, so load order is unaffected.
"""

import hmac
import os
import secrets

from flask import abort, current_app, request

TOKEN_COOKIE = "vibe_token"  # nosec B105  # cookie NAME (not a secret); the value is the token
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def install(app) -> None:
    """Give ``app`` its token and put every request behind the guard."""
    app.config["AUTH_TOKEN"] = os.environ.get("GENRE_TOKEN", "").strip() or secrets.token_urlsafe(
        32
    )
    app.before_request(_loopback_guard)
    app.after_request(_promote_token_cookie)


def launch_url(app, host: str, port: int) -> str:
    """The URL to open: the app's root with the token as ``?k=``. A wildcard bind
    is shown as 127.0.0.1, the address a browser on this machine should use (the
    guard refuses any Host that isn't loopback anyway)."""
    if host in ("", "0.0.0.0", "::"):  # nosec B104  # mapping a wildcard bind to loopback for display
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/?k={app.config['AUTH_TOKEN']}"


def _loopback_guard():
    token = current_app.config["AUTH_TOKEN"]
    host = (request.host or "").rsplit(":", 1)[0]
    if host not in _LOOPBACK_HOSTS:
        abort(403)  # not addressed to loopback -> likely DNS rebinding
    supplied = request.cookies.get(TOKEN_COOKIE) or request.args.get("k", "")
    if not hmac.compare_digest(supplied, token):
        abort(403)


def _promote_token_cookie(resp):
    # Turn a valid ?k= (the first navigation) into an httponly, same-site cookie
    # so later requests authenticate on their own, without the token in the URL.
    token = current_app.config["AUTH_TOKEN"]
    if hmac.compare_digest(request.args.get("k", ""), token):
        resp.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="Strict", path="/")
    return resp

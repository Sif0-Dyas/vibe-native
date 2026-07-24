"""Vibenative desktop shell — a native Windows window around the native app.

This is an ADDITIVE launcher. It does not modify any app code: it opens the exact
same Flask UI (served locally on a random loopback port) inside a chromeless native
window (Edge WebView2), boots the native backend for you if it isn't already
running, and injects a small JS shim at runtime that adds one thing a plain
browser can't do:

  * a native Windows *folder* picker whose picked ``C:\\...`` path is handed
    straight to the app's existing runBatch() (the native /batch route reads
    Windows paths directly now — no WSL translation).

Two backend modes (native ONNX engine, no WSL anywhere):

  * SINGLE-PROCESS (default; how the packaged .exe runs): the Flask app runs in a
    daemon thread inside THIS process — no child interpreter, no venv needed. This
    is what makes a standalone one-folder build possible.
  * TWO-PROCESS (fallback, GENRE_DESKTOP_MULTIPROC=1): spawn the project venv's
    Python running ``-m vibenative`` as a child, as earlier phases did. Kept because
    it's proven and handy in dev.

Both share the same localhost polling / splash / error-page flow.

Run:            pythonw genre_app.pyw        (or double-click "Vibe Identify.bat")
Self-test:      python  genre_app.pyw --selftest   (no window; checks the pure logic)

Config below (WIN_PROJECT / PORT) is the only thing you may need to edit for a
different machine.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import subprocess  # nosec B404  # only launches the project venv python with a fixed arg list, no shell
import sys
import threading
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Config — the only machine-specific knobs.
# --------------------------------------------------------------------------- #
# Port for this launch. If GENRE_PORT is set we honour it (a fixed custom port);
# otherwise configure() picks a free loopback port at launch so there is no
# predictable, well-known port sitting open. BASE_URL is recomputed in configure().
_FIXED_PORT = os.environ.get("GENRE_PORT")
PORT = int(_FIXED_PORT) if _FIXED_PORT else 5005
BASE_URL = f"http://127.0.0.1:{PORT}"

# Per-session shared secret. The backend (when handed GENRE_TOKEN) requires it on
# every request, so other local processes and malicious localhost web pages can't
# drive the API. A fresh random token is generated per launch unless one is given.
TOKEN = os.environ.get("GENRE_TOKEN", "")

# Windows-side location of the project = the folder that contains this desktop/
# dir. Deriving it from the script's own location (not a hardcoded path) means the
# shell boots whatever copy of the app it ships with — the original checkout, or a
# branch/worktree — so it's truly self-contained.
WIN_PROJECT = os.environ.get(
    "GENRE_WIN_PROJECT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

# FAKE_ANALYZER=1 in the backend => instant fake results, no model load. Handy for
# trying the shell without waiting on the ONNX models. Off by default.
FAKE = os.environ.get("GENRE_DESKTOP_FAKE", "") == "1"

# How long to wait for the backend to answer after we start it (importing
# onnxruntime + the first model touch can be slow on a cold start).
BOOT_TIMEOUT_S = int(os.environ.get("GENRE_BOOT_TIMEOUT", "150"))

CREATE_NO_WINDOW = 0x08000000  # keep a console from flashing up (Windows only)


def _backend_log_path() -> str:
    """Where the backend's startup log (incl. the 'execution provider: ...' line) is
    written, truncated per launch. In a packaged/installed build the exe sits in a
    read-only Program Files folder, so the log goes to a user-writable
    %LOCALAPPDATA%\\Vibenative\\ instead of beside the exe; in dev it's the project root."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.dirname(os.path.abspath(sys.executable))
        d = os.path.join(base, "Vibenative")
    else:
        d = WIN_PROJECT
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        import tempfile

        d = tempfile.gettempdir()
    return os.path.join(d, "desktop_backend.log")


BACKEND_LOG = _backend_log_path()


def _webview_storage_path():
    """Persistent WebView2 profile directory. pywebview defaults to
    private_mode=True (an ephemeral profile), which wipes IndexedDB on every
    launch — and with it the File System Access handles the app stores so
    dropped/browsed tracks stay playable across restarts. A stable profile keeps
    that data. Mirrors the backend-log location: %LOCALAPPDATA%\\Vibenative\\ when
    frozen, the project root in dev."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.dirname(os.path.abspath(sys.executable))
        d = os.path.join(base, "Vibenative", "webview")
    else:
        d = os.path.join(WIN_PROJECT, ".webview")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        import tempfile

        d = os.path.join(tempfile.gettempdir(), "vibenative-webview")
        os.makedirs(d, exist_ok=True)
    return d

_LAUNCH_WARNING: str | None = None  # set if we fall back off the project venv


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested by --selftest, no GUI / no backend needed).
# --------------------------------------------------------------------------- #
def venv_python() -> str:
    """The project venv's interpreter, resolved relative to the project root.

    Prefers ``<project>/.venv`` (Windows ``Scripts/python.exe``, POSIX
    ``bin/python``). Falls back to ``sys.executable`` and records a warning in
    ``_LAUNCH_WARNING`` (surfaced on the error page) when no project venv is found —
    that interpreter only works if it happens to have vibenative + deps installed.
    """
    global _LAUNCH_WARNING
    for sub in (("Scripts", "python.exe"), ("bin", "python")):
        cand = os.path.join(WIN_PROJECT, ".venv", *sub)
        if os.path.isfile(cand):
            return cand
    _LAUNCH_WARNING = (
        f"project venv not found under {os.path.join(WIN_PROJECT, '.venv')}; "
        f"falling back to {sys.executable} (analysis needs vibenative + its deps installed there)"
    )
    return sys.executable


def _free_loopback_port() -> int:
    """Ask the OS for an unused loopback port (bind :0, read it, release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def configure():
    """Fix the port + token for this launch: a free loopback port unless the user
    pinned GENRE_PORT, and a fresh per-session secret unless GENRE_TOKEN was set."""
    global PORT, BASE_URL, TOKEN
    if not _FIXED_PORT:
        PORT = _free_loopback_port()
    BASE_URL = f"http://127.0.0.1:{PORT}"
    if not TOKEN:
        TOKEN = secrets.token_urlsafe(24)


def backend_up() -> bool:
    """True if something is answering on the app's port. A 4xx (e.g. the 403 from
    the auth guard when we probe without the token) still means the server is up."""
    try:
        with urllib.request.urlopen(BASE_URL + "/", timeout=2) as r:  # nosec B310  # fixed 127.0.0.1 loopback probe
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def backend_cmd() -> list[str]:
    """The argv (list form => spaces are safe) that starts the native Flask backend:
    the project venv's Python running ``-m vibenative``."""
    return [venv_python(), "-m", "vibenative"]


def backend_env() -> dict:
    """Environment for the backend process: inherit ours, then pin the launch's port
    + token (and FAKE mode if requested)."""
    env = dict(os.environ)
    env["GENRE_PORT"] = str(PORT)
    env["GENRE_TOKEN"] = TOKEN
    if FAKE:
        env["FAKE_ANALYZER"] = "1"
    return env


_BACKEND_PROC: subprocess.Popen | None = None
_STARTED_BY_US = False  # True once we launch our own backend, so we can stop it


def start_backend() -> subprocess.Popen | None:
    """Launch ``python -m vibenative`` (project venv), detached and window-less.

    We deliberately do NOT kill this on exit unless we started it: if you already had
    the server running (your normal browser workflow) we reuse it, and leaving that
    up means the browser workflow keeps working after you close the desktop window.
    """
    global _BACKEND_PROC
    try:
        logf = open(BACKEND_LOG, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError:
        logf = subprocess.DEVNULL
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        _BACKEND_PROC = subprocess.Popen(  # nosec B603  # venv python + fixed args, no shell
            backend_cmd(),
            env=backend_env(),
            cwd=WIN_PROJECT,
            creationflags=flags,
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        return _BACKEND_PROC
    except (FileNotFoundError, OSError):
        return None  # interpreter not found


def _shutdown_backend():
    """Stop the backend we started (terminate our own child process precisely, so we
    never touch a server the user launched themselves). No-op if we reused one."""
    if not _STARTED_BY_US or _BACKEND_PROC is None:
        return
    try:
        _BACKEND_PROC.terminate()
        try:
            _BACKEND_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _BACKEND_PROC.kill()
    except Exception:  # nosec B110  # best-effort shutdown; a dead/unkillable child must not crash exit
        pass


# --------------------------------------------------------------------------- #
# Single-process backend: Flask in a daemon thread inside this process. This is
# the default and the ONLY mode the packaged .exe uses — no child interpreter, no
# venv on the target machine.
# --------------------------------------------------------------------------- #
def use_single_process() -> bool:
    """True (default) => run Flask in-process. Set GENRE_DESKTOP_MULTIPROC=1 to use
    the proven two-process fallback (spawn ``python -m vibenative``) instead. The
    packaged exe leaves this unset, so it runs single-process."""
    return os.environ.get("GENRE_DESKTOP_MULTIPROC", "") != "1"


def _ensure_std_streams():
    """A --windowed PyInstaller build gives sys.stdout/stderr == None; werkzeug's
    dev-server banner (and any stray print) writes to them and would crash with
    'NoneType has no write'. Point them at a sink so those writes are harmless."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
            except OSError:
                pass


def _setup_inprocess_logging():
    """Route the in-process backend's logs (incl. onnx_engine's 'execution
    provider: ...' line) to BACKEND_LOG, matching what the two-process child wrote
    to that file — so the same log is inspectable either way. --windowed builds have
    no console, so a file is the only place these land."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        fh = logging.FileHandler(BACKEND_LOG, mode="w", encoding="utf-8")
    except OSError:
        return
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)


def _start_inprocess() -> threading.Thread:
    """Create the Flask app and serve it on this launch's port in a daemon thread.

    The pinned port/token/FAKE flag are pushed into the environment BEFORE importing
    vibenative, because config.py / db.py / the loopback auth guard read them at
    import time. The daemon thread dies automatically when the window closes."""
    os.environ["GENRE_PORT"] = str(PORT)
    os.environ["GENRE_TOKEN"] = TOKEN
    if FAKE:
        os.environ["FAKE_ANALYZER"] = "1"
    _ensure_std_streams()
    _setup_inprocess_logging()
    log = logging.getLogger("vibenative")

    import vibenative  # bundled in the exe; editable-installed in the dev venv

    app = vibenative.create_app()
    if not FAKE:
        from vibenative.decode import find_tool

        missing = [t for t in ("ffmpeg", "ffprobe") if not find_tool(t)]
        if missing:
            log.warning(
                "%s not found (PATH / exe-adjacent / WinGet) -- audio decode will fail. "
                "New analysis needs ffmpeg; cached tracks still load.",
                " + ".join(missing),
            )
    log.info("Vibenative running in-process -> %s", BASE_URL)

    def _run():
        # use_reloader=False: never fork a reloader from a daemon thread.
        app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)

    t = threading.Thread(target=_run, name="vibenative-flask", daemon=True)
    t.start()
    return t


def _ensure_backend_started() -> tuple[bool, str | None]:
    """Bring a backend up (or reuse one already answering). Returns (ok, error_html
    detail). Single-process by default; two-process fallback when requested."""
    global _STARTED_BY_US
    if backend_up():
        return True, None  # something's already serving our port -> reuse it
    if use_single_process():
        try:
            _start_inprocess()
        except Exception as e:  # import/bind failure -> show it rather than hang
            return False, f"<b>the in-process backend failed to start:</b> {e}"
        _STARTED_BY_US = True
        return True, None
    if start_backend() is None:
        return False, "<b>Could not launch the backend interpreter.</b>"
    _STARTED_BY_US = True
    return True, None


# --------------------------------------------------------------------------- #
# The JS shim injected into the live page (only inside this shell). It wires the
# native folder picker to the app's existing runBatch(). Nothing here touches app.js.
# --------------------------------------------------------------------------- #
INJECT_JS = r"""
(function () {
  if (window.__vibeDesk) return;            // idempotent across reloads
  if (!window.pywebview || !window.pywebview.api) return;
  window.__vibeDesk = true;
  document.body.classList.add('desktop-shell');

  // Drop the one-time ?k=<token> from the address so it isn't left in history.
  try {
    if (location.search.indexOf('k=') !== -1) {
      history.replaceState({}, '', location.pathname + location.hash);
    }
  } catch (e) {}

  // 1) Intercept the "batch folder" button BEFORE its own prompt() handler runs.
  //    A capture-phase listener on document fires ahead of the target's own
  //    click listener, so stopImmediatePropagation() cleanly preempts it.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('#batch-btn') : null;
    if (!btn) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    Promise.resolve(window.pywebview.api.pick_folder()).then(function (winPath) {
      if (winPath && typeof window.runBatch === 'function') {
        window.runBatch(winPath);
      }
    });
  }, true);

  // (The "add files" picker the app already has in its footer — "Browse files" —
  //  opens the same native Windows file dialog, so the shell no longer injects a
  //  duplicate button.)
})();
"""

# Splash + error pages shown while the backend is (not) coming up. Kept inline so
# the shell is a single self-contained file.
LOADING_HTML = """
<!doctype html><meta charset="utf-8">
<title>Vibedentify</title>
<!-- Palette taken from the ACTIVE :root in vibenative/static/app.css — the
     "Neon-DJ" theme whose :root overrides the earlier WINAMP SKIN block: chassis
     --bg #06080D, panel --panel #0C1016, hairline --line #1E2632, text
     --text #EAF2F8, dim --dim #7C8998, cyan --accent-a #22D3EE + violet
     --accent-b #7C5CFF, LCD --lcd #5DE9FF on well --lcd-bg #03141B. -->
<style>
  html,body{height:100%;margin:0;background:#06080D;color:#EAF2F8;
    font:15px/1.5 system-ui,'Segoe UI',sans-serif;display:grid;place-items:center}
  /* flat panel + hairline border + cyan glow, matching the Neon-DJ chassis */
  .box{text-align:center;background:#0C1016;padding:28px 44px;
    border:1px solid #1E2632;border-radius:12px;box-shadow:0 0 10px rgba(34,211,238,.35)}
  /* wordmark: cyan->violet gradient text with a cyan glow, like the app header */
  h1{margin:0 0 6px;font-weight:800;letter-spacing:-.01em;color:#22D3EE;
    background:linear-gradient(90deg,#22D3EE,#7C5CFF);
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
    filter:drop-shadow(0 0 10px rgba(34,211,238,.5))}
  p{color:#7C8998;margin:.3em 0}
  /* dark cyan-tinted LCD well holding the readout dots, like the app's BPM cell */
  .lcd{display:inline-block;margin-top:12px;padding:9px 13px;background:#03141B;
    border:1px solid rgba(34,211,238,.20);border-radius:6px}
  .dot{width:9px;height:9px;border-radius:50%;background:#5DE9FF;display:inline-block;
    margin:0 3px;box-shadow:0 0 8px rgba(93,233,255,.7);animation:p 1s infinite ease-in-out}
  .dot:nth-child(2){animation-delay:.15s}.dot:nth-child(3){animation-delay:.3s}
  @keyframes p{0%,80%,100%{opacity:.25;transform:translateY(0)}40%{opacity:1;transform:translateY(-5px)}}
</style>
<div class="box">
  <h1>Vibedentify</h1>
  <p id="msg">Starting the analysis engine&hellip;</p>
  <div class="lcd"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
</div>
"""


def error_html(detail: str) -> str:
    if getattr(sys, "frozen", False):
        # packaged exe: no venv / no `python -m` to run by hand
        manual = (
            f"<p>The full backend log is at <code>{BACKEND_LOG}</code> — it has the real "
            f"error. Make sure <code>models/</code> sits next to the exe.</p>"
        )
    else:
        py = venv_python()
        manual = (
            "<p>Start it by hand to see the error, then relaunch this app:</p>"
            f'<ul><li><code>cd "{WIN_PROJECT}"</code></li>'
            f"<li><code>{py} -m vibenative</code></li></ul>"
            f"<p>The full backend log is at <code>{BACKEND_LOG}</code>. Check "
            f"<code>WIN_PROJECT</code> at the top of <code>genre_app.pyw</code> if the paths "
            f"above look wrong.</p>"
        )
    return f"""
<!doctype html><meta charset="utf-8"><title>Vibedentify — can't start</title>
<!-- Palette taken from the ACTIVE :root in vibenative/static/app.css — the
     "Neon-DJ" theme whose :root overrides the earlier WINAMP SKIN block: chassis
     --bg #06080D, panel --panel #0C1016, hairline --line #1E2632, text
     --text #EAF2F8, dim --dim #7C8998, warn/gold --gold #FFC46B, LCD --lcd
     #5DE9FF on well --lcd-bg #03141B. -->
<style>
  html,body{{height:100%;margin:0;background:#06080D;color:#EAF2F8;
    font:15px/1.6 system-ui,'Segoe UI',sans-serif;display:grid;place-items:center}}
  .box{{max-width:640px;padding:26px 32px;background:#0C1016;
    border:1px solid #1E2632;border-radius:12px;box-shadow:0 0 10px rgba(34,211,238,.25)}}
  /* amber heading — the Neon-DJ theme reserves --gold for alerts, so it reads as a warning */
  h1{{color:#FFC46B;font-weight:800;letter-spacing:-.01em}}
  p{{color:#7C8998}}
  /* code shown like the app's cyan LCD readouts: on a dark cyan-tinted well, mono */
  code{{color:#5DE9FF;background:#03141B;
    font-family:ui-monospace,Consolas,'Courier New',monospace;
    padding:2px 7px;border:1px solid rgba(34,211,238,.20);border-radius:5px;
    display:inline-block;margin:2px 0;text-shadow:0 0 6px rgba(93,233,255,.4)}}
  li{{margin:.4em 0}}
</style>
<div class="box">
  <h1>Couldn't reach the analysis engine</h1>
  <p>The desktop window is fine, but the Vibedentify backend on
     <code>{BASE_URL}</code> didn't come up within {BOOT_TIMEOUT_S}s.</p>
  <p>{detail}</p>
  {manual}
</div>
"""


# --------------------------------------------------------------------------- #
# GUI (pywebview). Imported lazily so --selftest runs without pywebview present.
# --------------------------------------------------------------------------- #
class Api:
    """Methods callable from the page as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None

    def bind(self, window):
        self._window = window

    def pick_folder(self):
        """Native Windows folder dialog -> Windows path string ('' if cancelled).

        The native /batch route reads ``C:\\...`` paths directly, so the picked path
        is handed through unchanged (no WSL /mnt translation anymore)."""
        import webview

        start_dir = os.path.join(os.path.expanduser("~"), "Music")
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=start_dir)
        if not result:
            return ""
        return result[0] if isinstance(result, (list, tuple)) else result


def _boot_and_load(window):
    """Runs in pywebview's worker thread once the GUI is up: ensure the backend is
    answering (single-process thread, or two-process child), then navigate the
    window to the real app."""
    ok, err = _ensure_backend_started()
    if not ok:
        window.load_html(error_html(err))
        return
    started = _STARTED_BY_US

    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline:
        if backend_up():
            # first navigation carries the token as ?k=; the backend promotes it
            # to an httponly cookie and INJECT_JS strips it back off the URL.
            window.load_url(f"{BASE_URL}/{('?k=' + TOKEN) if TOKEN else ''}")
            return
        time.sleep(0.6)

    # Timed out.
    if use_single_process():
        detail = (
            "The in-process engine started but never answered within the timeout — the "
            "first cold start can be slow while onnxruntime and the models load. See the "
            "backend log for the real error."
        )
    elif not os.path.isdir(WIN_PROJECT):
        detail = (
            f"<b>the configured project folder was not found: <code>{WIN_PROJECT}</code></b>"
            f" — edit <code>GENRE_WIN_PROJECT</code> / <code>WIN_PROJECT</code> to point at "
            f"your checkout."
        )
    elif _LAUNCH_WARNING:
        detail = f"<b>{_LAUNCH_WARNING}</b>"
    elif started:
        detail = (
            "We launched it but it never answered — the first cold start can be slow "
            "while onnxruntime and the models load."
        )
    else:
        detail = "It doesn't look like it's running."
    window.load_html(error_html(detail))


def main():
    _ensure_std_streams()  # frozen --windowed: guard None stdout/stderr before anything writes
    import webview

    configure()  # pick this launch's port + token before anything uses BASE_URL
    api = Api()
    window = webview.create_window(
        "Vibedentify",
        html=LOADING_HTML,
        js_api=api,
        width=1280,
        height=860,
        min_size=(900, 600),
        background_color="#06080D",  # Neon-DJ --bg, matches the splash chassis
    )
    api.bind(window)

    def on_loaded():
        try:
            url = window.get_current_url() or ""
        except Exception:
            url = ""
        if url.startswith(BASE_URL):
            window.evaluate_js(INJECT_JS)

    window.events.loaded += on_loaded
    # private_mode=False + a stable storage_path so IndexedDB (which holds the
    # File System Access handles for replayable dropped tracks) persists.
    webview.start(_boot_and_load, window, private_mode=False, storage_path=_webview_storage_path())
    _shutdown_backend()  # window closed -> stop the backend we launched


# --------------------------------------------------------------------------- #
# Self-test: exercises the pure logic without a window or a running backend.
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  [{'ok' if good else 'XX'}] {name}: {got!r}")
        if not good:
            print(f"        expected {want!r}")

    print("project + venv resolution:")
    print(f"  WIN_PROJECT = {WIN_PROJECT!r}")
    py = venv_python()
    print(f"  venv_python = {py!r}  | warning: {_LAUNCH_WARNING!r}")
    venv_dir = os.path.join(WIN_PROJECT, ".venv")
    if os.path.isdir(venv_dir):
        # a real project venv is present (this dev machine): resolve into it, no warning
        check("resolves inside project .venv", os.path.commonpath([py, venv_dir]) == venv_dir, True)
        check("no fallback warning when venv present", _LAUNCH_WARNING, None)
    else:
        # CI / a checkout with no venv: fall back to sys.executable with a warning
        check("falls back to sys.executable", py, sys.executable)
        check("records a fallback warning", bool(_LAUNCH_WARNING), True)

    print("process mode:")
    os.environ.pop("GENRE_DESKTOP_MULTIPROC", None)
    check("single-process is the default", use_single_process(), True)
    os.environ["GENRE_DESKTOP_MULTIPROC"] = "1"
    check("two-process fallback via GENRE_DESKTOP_MULTIPROC=1", use_single_process(), False)
    os.environ.pop("GENRE_DESKTOP_MULTIPROC", None)
    check("back to single-process once unset", use_single_process(), True)

    print("two-process fallback launch command (native, no WSL):")
    cmd = backend_cmd()
    print("  ", cmd)
    check("runs the native module", cmd[-2:], ["-m", "vibenative"])
    check("interpreter is the resolved python", cmd[0], py)
    check("no wsl anywhere in argv", not any("wsl" in str(a).lower() for a in cmd), True)

    print("backend environment:")
    configure()
    env = backend_env()
    check("passes GENRE_PORT", env.get("GENRE_PORT"), str(PORT))
    check("passes GENRE_TOKEN", env.get("GENRE_TOKEN"), TOKEN)
    check("FAKE off by default -> no FAKE_ANALYZER", "FAKE_ANALYZER" in env, FAKE)

    print("port + token (configure):")
    check("free port is int > 1024", isinstance(PORT, int) and PORT > 1024, True)
    check("base url tracks port", BASE_URL, f"http://127.0.0.1:{PORT}")
    check("token generated", len(TOKEN) >= 24, True)

    print("no WSL path translation remains:")
    check("win_to_wsl helper is gone", "win_to_wsl" in globals(), False)
    check("no /mnt in the launch command", not any("/mnt/" in str(a) for a in cmd), True)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    main()

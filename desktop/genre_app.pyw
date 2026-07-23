"""Vibenative desktop shell — a native Windows window around the native app.

This is an ADDITIVE launcher. It does not modify any app code: it opens the exact
same Flask UI (served locally on a random loopback port) inside a chromeless native
window (Edge WebView2), boots the native backend for you if it isn't already
running, and injects a small JS shim at runtime that adds two things a plain
browser can't do:

  * a native Windows *folder* picker whose picked ``C:\\...`` path is handed
    straight to the app's existing runBatch() (the native /batch route reads
    Windows paths directly now — no WSL translation),
  * an always-visible "add files" button that reuses the app's existing native
    file picker (#picker) + enqueue() upload path.

The backend is the project venv's Python running ``-m vibenative`` (native ONNX
engine — no WSL anywhere).

Run:            pythonw genre_app.pyw        (or double-click "Vibe Identify.bat")
Self-test:      python  genre_app.pyw --selftest   (no window; checks the pure logic)

Config below (WIN_PROJECT / PORT) is the only thing you may need to edit for a
different machine.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess  # nosec B404  # only launches the project venv python with a fixed arg list, no shell
import sys
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

# The backend's own stdout/stderr are captured here (truncated per launch) so its
# startup log — including the "execution provider: ..." line — is inspectable.
BACKEND_LOG = os.path.join(WIN_PROJECT, "desktop_backend.log")

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
# The JS shim injected into the live page (only inside this shell). It wires the
# native folder picker to the app's existing runBatch(), and adds an "add files"
# button that reuses the app's own #picker. Nothing here touches app.js on disk.
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

  // 2) Add an always-visible "add files" button next to the batch button that
  //    reuses the app's existing native file picker (#picker) + upload path.
  var batchBtn = document.getElementById('batch-btn');
  var picker = document.getElementById('picker');
  if (batchBtn && picker && !document.getElementById('desk-addfiles')) {
    var b = document.createElement('button');
    b.type = 'button';
    b.id = 'desk-addfiles';
    b.textContent = '♪ add files';
    b.title = 'Pick audio files (native Windows dialog)';
    batchBtn.insertAdjacentElement('afterend', b);
    b.addEventListener('click', function () { picker.click(); });
  }
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
    py = venv_python()
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
  <p>Start it by hand to see the error, then relaunch this app:</p>
  <ul>
    <li><code>cd "{WIN_PROJECT}"</code></li>
    <li><code>{py} -m vibenative</code></li>
  </ul>
  <p>The full backend log is at <code>{BACKEND_LOG}</code>. Check
     <code>WIN_PROJECT</code> at the top of <code>genre_app.pyw</code> if the paths
     above look wrong.</p>
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
    answering, then navigate the window to the real app."""
    global _STARTED_BY_US
    started = False
    if not backend_up():
        if start_backend() is None:
            window.load_html(error_html("<b>Could not launch the backend interpreter.</b>"))
            return
        started = _STARTED_BY_US = True

    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline:
        if backend_up():
            # first navigation carries the token as ?k=; the backend promotes it
            # to an httponly cookie and INJECT_JS strips it back off the URL.
            window.load_url(f"{BASE_URL}/{('?k=' + TOKEN) if TOKEN else ''}")
            return
        time.sleep(0.6)

    # Timed out. Most common misconfigurations: a wrong project path, or a missing
    # project venv (so the backend interpreter had no vibenative/deps).
    if not os.path.isdir(WIN_PROJECT):
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
    webview.start(_boot_and_load, window)
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

    print("backend launch command (native, no WSL):")
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

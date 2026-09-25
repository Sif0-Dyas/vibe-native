# Vibedentify — Windows desktop shell

A native, chromeless Windows window around the Vibenative app. It does **not**
change any app code: it opens the same UI (served locally on a random loopback
port) in an Edge WebView2 window, starts the native backend for you if it isn't
already running, and adds two things a plain browser can't do.

```
 Vibe Identify.bat   ──►  pythonw genre_app.pyw
                            ├─ probe http://127.0.0.1:<port>
                            ├─ if down: <project>/.venv python -m vibenative
                            ├─ show splash until it answers
                            ├─ open the app in a native window (no browser chrome)
                            └─ inject JS:  ⊕ batch folder → native folder dialog
                                           ♪ add files    → native file dialog
```

No WSL anywhere: the backend is the project venv's Python running the native ONNX
engine (`-m vibenative`).

## What it adds

| Button | Plain browser | In this shell |
| --- | --- | --- |
| **⊕ batch folder** | text prompt: *type a folder path* | **native Windows folder dialog**; the picked `C:\…` folder is handed straight to the app's existing `runBatch()` (the native `/batch` route reads Windows paths directly) |
| **♪ add files** | (only the drop zone / empty-state click) | always-visible button that opens the **native file dialog** and reuses the app's existing upload path |

Everything else — the list, the Map, waveforms, playback — is the unchanged web app.

## One-time setup

1. Install the runtime + shell deps into the **project venv** (the same venv that
   runs the analysis engine) from `uv.lock`:
   ```
   uv sync --group desktop
   ```
   (The Edge WebView2 runtime is already on Windows 11.)
2. Double-click **`Vibe Identify.bat`** at the project root.

To make it feel installed: right-click `Vibe Identify.bat` → *Create shortcut*, then
pin the shortcut to Start / the taskbar.

## Configuration

The only machine-specific values live at the top of `genre_app.pyw`, each also
overridable by an environment variable:

| Constant | Env var | Default |
| --- | --- | --- |
| `WIN_PROJECT` | `GENRE_WIN_PROJECT` | *auto-detected: the folder containing `desktop/`* |
| `PORT` | `GENRE_PORT` | *random free loopback port* (set to pin one) |
| `TOKEN` | `GENRE_TOKEN` | *fresh per-session secret* (set to pin one) |
| `FAKE` | `GENRE_DESKTOP_FAKE=1` | off (real analysis) |
| `BOOT_TIMEOUT_S` | `GENRE_BOOT_TIMEOUT` | `150` seconds |

`WIN_PROJECT` defaults to this script's own project folder, so the shell boots
whichever copy of the app it ships with (this branch/worktree, or another checkout).
The backend interpreter is resolved as `<WIN_PROJECT>/.venv` — Windows
`Scripts\python.exe` — and falls back to whatever Python launched the shell (with a
warning on the error screen) if no project venv is found.

Set `GENRE_DESKTOP_FAKE=1` to boot the backend in fake-analyzer mode (instant
results, no model load) — handy for trying the window itself.

## Security model

The shell runs the backend **locked down**, so it isn't just "a web server on
localhost anyone on your PC can poke":

- **Random loopback port.** Each launch binds a fresh, unused `127.0.0.1` port —
  never your LAN. No predictable, well-known port sits open. Pin one with
  `GENRE_PORT` if you need it stable.
- **Per-session secret token.** The shell generates a random token and hands it to
  the backend (`GENRE_TOKEN`). Every request must carry it — the first navigation
  passes `?k=<token>`, which the backend promotes to an httponly, `SameSite=Strict`
  cookie; the shell then strips the token from the URL. Other local processes and
  malicious localhost web pages don't have it, so they get **403**.
- **Host-header check.** Requests not addressed to a loopback host are rejected
  (403), defeating DNS-rebinding.

The token and Host checks are **always on in the backend**, for every request
including `/static/*` (`vibenative/auth.py`). The shell's only part is choosing the
token and passing it in; a backend started any other way generates its own.

> Trade-off: because the shell's token is private to it, you can't open its random
> port in a normal browser tab. Run `uv run python -m vibenative` yourself for a
> browsable instance on `:5005` -- it prints the `?k=<token>` URL to open.

## Notes / behavior

- **Own server, cleaned up.** The shell starts its own backend on the random port
  and **stops it when you close the window** (it terminates precisely the child
  process it started, so a server you launched yourself is never touched). If its
  port somehow already answers, it just attaches and won't kill on exit.
- **Backend log.** The backend's stdout/stderr — including the
  `execution provider: …` line showing whether DirectML or CPU engaged — is written
  to `desktop_backend.log` at the project root (truncated per launch).
- **Cold start can take a while** the first time (onnxruntime import + model load).
  The splash waits up to `BOOT_TIMEOUT_S` (150 s) before showing a help screen.
- **Audio playback:** folder scans store the on-disk Windows path, so playback
  works; individual files added via *add files* upload their bytes (same as browser
  drag-drop) and have no server-side path, so scan the folder if you want previews.

## Verify without opening a window

```
python genre_app.pyw --selftest
```

Runs the venv-resolution and launch-command logic and prints PASS/FAIL. No GUI, no
backend, no pywebview needed — this is what CI runs.

## Packaging to a standalone .exe (optional, out of scope)

PyInstaller could later fold this into a single `Vibedentify.exe`:

```
uv sync --group desktop
uv run pyinstaller --noconsole --onefile --name Vibedentify desktop\genre_app.pyw
```

The resulting `dist\Vibedentify.exe` launches like installed software (still needs
the project venv + models for analysis). Not built or tested here — a future option.

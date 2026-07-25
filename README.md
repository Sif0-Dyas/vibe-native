# Vibe Native

Native-Windows rebuild of [Vibe_Identify](https://github.com/Sif0-Dyas/Vibe_Identify)'s
analysis engine: ONNX Runtime (+ DirectML GPU) instead of Essentia, same app,
same database, no WSL.

**Status: shipped as a standalone Windows executable.** Essentia is gone; the app
runs natively via ONNX Runtime (DirectML on an RTX 5070) inside a chromeless desktop
window, and packages to a self-contained `dist\Vibe Identify\` folder — no Python,
no venv, no WSL on the target machine (Flask runs in-process behind the exe; DirectML
GPU works in the packaged build). Validated against the WSL build as the oracle:

- **Genre** — native mel frontend + EffNet/Discogs-400 head reproduce the oracle
  embeddings to **cosine > 0.999 on all 121 tracks** (worst 0.99932); the converted
  head matches the oracle's top styles exactly (worst |Δscore| 5.96e-08).
- **Tempo** — TempoCNN within 2% or an octave for **96.7%** of tracks (≥95% bar).
- **Key** — a faithful port of Essentia's KeyExtractor matches key + scale on
  **121/121 tracks (100%)**.
- **App** — same routes, DB schema, and frontend as Vibe_Identify; the whole Flask
  app + the pywebview desktop shell run on one Windows venv in dev, or as a single
  packaged `.exe` (PyInstaller onedir), **no WSL anywhere**. GPU falls out for free
  (`DmlExecutionProvider`, loud CPU fallback).

Design + phase-by-phase details (historical, now complete):
[`docs/history/PROJECT_PLAN.md`](docs/history/PROJECT_PLAN.md) and
[`docs/history/PLAN_ADDENDUM.md`](docs/history/PLAN_ADDENDUM.md). Live conversion
reference stays at `tools/CONVERSION_NOTES.md`. The original WSL app stays untouched
as the oracle and the rollback.

## Project layout

Standard `src/` layout — the importable `vibenative` package lives under `src/`:

```
src/vibenative/        the package: Flask app factory + config/db, the ONNX engine
                       (decode · frontend_mel · onnx_engine · tempo · key), and
  routes/              one Blueprint, split by domain: analysis, library, vibes,
                       tags, playlists, map, training
  templates/ static/   the web UI (bundled into the exe as data files)
desktop/               pywebview desktop shell (genre_app.pyw) + launcher
tools/                 build (build_exe.py · build_installer.py), model conversion,
                       oracle + db-cutover helpers
tests/                 pytest suite (FAKE mode by default; real-mode tests skip
                       without models)
models/                ONNX models (git-ignored; `python tools/convert_models.py`)
docs/                  USAGE.md guide + history/ (completed plan docs)
Vibe Identify.spec     PyInstaller onedir spec (packages src/vibenative + assets)
```

## Running it

Native Windows, no WSL. One-time setup (the venv runs both the engine and the
desktop shell):

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r desktop\requirements-desktop.txt
.venv\Scripts\python -m pip install -e .        # makes `python -m vibenative` importable
```

Requires **ffmpeg** on PATH (`winget install Gyan.FFmpeg`) for audio decode, and
the ONNX models in `models/` (`python tools/convert_models.py`). The Edge WebView2
runtime ships with Windows 11.

**Desktop app** — double-click **`Vibe Identify.bat`** (project root). It opens the
UI in a native window, boots the backend for you, and shows a splash until it's
ready. See `desktop/README.md` for the folder-picker / security details.

**Browser / headless** — run the backend yourself and open it in a browser:

```
.venv\Scripts\python -m vibenative        # serves http://127.0.0.1:5005
```

`FAKE_ANALYZER=1` serves instant fake results (no models). The library database is
read from `GENRE_DB` (default `%USERPROFILE%\genre_v2.db`); bring an existing WSL
library over once with `python tools/db_cutover.py`.

**ffmpeg** is required for audio decode. In dev it's found on PATH (or the WinGet
Links dir). In a packaged build it sits **next to the exe** — `tools/prepare_dist.py`
copies the system ffmpeg in and writes a `ffmpeg-NOTICE.txt`. ffmpeg is invoked as a
separate program (argv), never linked in, so it stays a mere aggregation; a winget
"Gyan.FFmpeg" build is typically **GPL**, so for redistribution prefer an **LGPL**
shared build (gyan.dev "shared" / BtbN LGPL) or drop the bundled copy and rely on a
system-PATH ffmpeg. If ffmpeg is absent the app still runs (cached browsing works)
and warns that new analysis needs it.

## Development

Run the same gate CI does before pushing:

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
ruff check . && ruff format --check .    # lint + format (CI fails the build on either)
pytest -q                                 # tests (FAKE_ANALYZER covers the model-free path)
```

**Pre-commit hooks** make the format gate structurally impossible to miss — install
them once and `git commit` auto-runs `ruff check` + `ruff format` on staged files:

```
pip install pre-commit && pre-commit install
```

The hook config lives in `.pre-commit-config.yaml` (Python/ruff only; the JS eslint
check runs in CI).

## Building the executable

Package the app as a **standalone Windows folder** — no Python, no venv on the
target machine. The desktop shell runs Flask in-process (a daemon thread), so the
whole thing is one process behind `Vibe Identify.exe`.

```
.venv\Scripts\python -m pip install -r requirements-dev.txt   # brings PyInstaller
.venv\Scripts\python tools\build_exe.py
```

That runs PyInstaller against `Vibe Identify.spec` (one-folder / **onedir**), then
`tools/prepare_dist.py` copies the ONNX models and the system ffmpeg **beside the
exe** (they are deliberately *not* baked into the bundle), and prints the final
folder + size. Result: `dist\Vibe Identify\` — double-click `Vibe Identify.exe`.

Notes:
- **onedir, not onefile** — onefile re-extracts hundreds of MB of native DLLs to a
  temp dir on every launch (slow) and breaks exe-adjacent resource resolution; onedir
  keeps `models\` and `ffmpeg.exe` in a stable folder next to the exe. See the spec
  header.
- **GPU** — the DirectML EP (`DirectML.dll`) is bundled; the app uses
  `DmlExecutionProvider` and falls back to CPU (logged loudly) only if it can't load.
- **models** — must exist in `models\` first (`python tools\convert_models.py`).
- **ffmpeg licensing** — see the ffmpeg note above; a `ffmpeg-NOTICE.txt` ships in the
  folder.
- The build is **manual** and intentionally not part of CI (too heavy).

## Installer

Wrap the folder in a proper Windows installer (Inno Setup):

```
.venv\Scripts\python tools\build_installer.py --build
```

`--build` runs `tools\build_exe.py` first; then it stamps the version from
`vibenative.__version__` and runs Inno's `iscc` on `tools\installer.iss`, producing
`dist\installer\VibeIdentify-Setup-<version>.exe` (~178 MB). Needs **Inno Setup 6** —
if `iscc` isn't found the script prints `winget install --id JRSoftware.InnoSetup -e`.

**Requirements (enforced by the installer):**
- **64-bit Windows 10 version 1903 (build 18362) or newer** — older/32-bit is refused
  with a clear message.
- **Edge WebView2 runtime** — ships with Windows 11; on Windows 10 the installer
  downloads and runs Microsoft's Evergreen bootstrapper automatically if it's missing.
- ~1.5 GB free during install (the folder is ~540 MB; models + LGPL ffmpeg included).

**What it does:** installs to `C:\Program Files\Vibe Identify`, adds a Start-menu
shortcut (desktop shortcut optional), and includes a proper uninstaller. A wizard page
asks where your **music database** lives (default: your user profile,
`%USERPROFILE%\genre_v2.db`) — an existing library there is reused. Power users can
still set the `GENRE_DB` environment variable to override. The database and analysis
data live **outside** the install folder, so upgrading or reinstalling never touches
them; the **uninstaller** asks whether to remove your data and defaults to **No**.

**SmartScreen & antivirus (unsigned build):** the installer and exe are not
code-signed, so the first launch on another machine shows **“Windows protected your
PC.”** Click **More info → Run anyway**. Some antivirus engines occasionally
false-positive on unsigned PyInstaller executables — if flagged, allow/exclude
`Vibe Identify.exe`. Signing with a real code-signing certificate removes both prompts
(out of scope here).

## License & third-party components

This repository's **first-party code is MIT-licensed** (see [`LICENSE`](LICENSE)).
That covers the app, routes, desktop shell, build tooling, and tests. It does **not**
cover the following third-party components, which keep their own licenses:

- **ML models** — the genre (Discogs-EffNet / Discogs-400), tempo (TempoCNN), and
  related models are **MTG's**, released under **CC BY-NC-ND 4.0** (non-commercial,
  no-derivatives). They are downloaded/converted by `tools/convert_models.py`, live in
  `models/`, and are **not** covered by this repo's MIT license. Their terms —
  including the **non-commercial** restriction — govern any use or redistribution of
  the models themselves.
- **Essentia-derived algorithm ports** — `src/vibenative/key.py` and parts of
  `src/vibenative/frontend_mel.py` were **ported stage-for-stage from Essentia**
  (MTG), which is licensed **AGPL-3.0**. As derivative works of AGPL code, these files
  follow **Essentia's AGPL-3.0** upstream license, **not** MIT. If you reuse or
  redistribute them, treat them as AGPL-3.0.
- **ffmpeg** — invoked as a separate program (never linked), so it stays a mere
  aggregation; a bundled build ships with its own `ffmpeg-NOTICE.txt`. Prefer an
  **LGPL** shared build for redistribution (see the ffmpeg note under *Running it*).

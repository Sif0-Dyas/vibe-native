# Vibe Native

Native-Windows rebuild of [Vibe_Identify](https://github.com/Sif0-Dyas/Vibe_Identify)'s
analysis engine: ONNX Runtime (+ DirectML GPU) instead of Essentia, same app,
same database, no WSL.

**Status: shipped.** Essentia is gone; the app runs natively on Windows via ONNX
Runtime (DirectML on an RTX 5070), inside a chromeless desktop window. Validated
against the WSL build as the oracle:

- **Genre** — native mel frontend + EffNet/Discogs-400 head reproduce the oracle
  embeddings to **cosine > 0.999 on all 121 tracks** (worst 0.99932); the converted
  head matches the oracle's top styles exactly (worst |Δscore| 5.96e-08).
- **Tempo** — TempoCNN within 2% or an octave for **96.7%** of tracks (≥95% bar).
- **Key** — a faithful port of Essentia's KeyExtractor matches key + scale on
  **121/121 tracks (100%)**.
- **App** — same routes, DB schema, and frontend as Vibe_Identify; the whole Flask
  app + the pywebview desktop shell run on one Windows venv, **no WSL anywhere**.
  GPU falls out for free (`DmlExecutionProvider`, CPU fallback).

Design + phase-by-phase details: `PROJECT_PLAN.md`, `PLAN_ADDENDUM.md`, and
`tools/CONVERSION_NOTES.md`. The original WSL app stays untouched as the oracle and
the rollback.

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

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

A standalone single-`.exe` via PyInstaller is a possible future convenience — out
of scope here (the `.bat` + venv is the supported launch).

# Vibe Native

Native-Windows rebuild of [Vibe_Identify](https://github.com/Sif0-Dyas/Vibe_Identify)'s
analysis engine: ONNX Runtime (+ DirectML GPU) instead of Essentia, same app,
same database, no WSL.

**Status: planned, not started.** Read `PROJECT_PLAN.md` — it contains the
full architecture, the phase-by-phase roadmap, and the Claude Code prompt for
each session. Start with Phase 0 (`tools/make_oracle.py`, run on the existing
WSL install), then Session A.

The existing WSL app is the validation oracle; nothing here changes it.

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

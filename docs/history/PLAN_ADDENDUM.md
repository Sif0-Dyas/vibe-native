# PLAN ADDENDUM — reconciling with Vibe_Identify as of late July 2026

> **Historical — complete.** A mid-project course-correction to the plan above; its
> revisions all landed in the shipped app. Kept for provenance. Archived 2026-07-25.

Read PROJECT_PLAN.md first; this file corrects its drift. The plan was written
~30 commits ago. Everything below supersedes the corresponding plan sections.

## 1. The endgame changed: the desktop shell already exists

Vibe_Identify now has `desktop/genre_app.pyw` — a pywebview/WebView2 window
that launches the backend, polls readiness, and hosts the UI with a native
folder picker injected over the batch button. **This is the native app's
window.** Phase 5 therefore shrinks to:

- Port the shell; replace its WSL launch (`wsl.exe -e ... python -m
  vibedentify`) with `[sys.executable, "-m", "vibenative"]` on Windows Python.
- Delete `win_to_wsl` path translation entirely — native backend reads
  `C:\...` directly. The injected folder-picker stays (it's still nicer than
  a prompt) but passes the Windows path through unchanged.
- The shell's selftest, boot-timeout, error-page, and additive-only design
  carry over as-is.

End state: ONE tray of Windows Python + a .pyw. No WSL anywhere.

## 2. Model conversion got easier (Phase 1 update)

- The EffNet embedder now ships as `discogs-effnet-bs64-1-savedmodel.zip`.
  Convert from the SavedModel, not the frozen .pb — tf2onnx handles
  SavedModels without manual --inputs/--outputs tensor flags. The plan's
  "Risks" note about tensor names likely becomes unnecessary; keep it as
  fallback if the SavedModel path fails.
- MTG has begun publishing ready-made .onnx files for some models (the
  genre_discogs400 and 519 heads exist as .onnx for MAEST embeddings).
  During Session A, CHECK whether an effnet-variant .onnx of the 400 head
  has appeared before converting anything — a download beats a conversion.
- TempoCNN ships .pb + tfjs; convert the .pb (deeptemp-k16) via tf2onnx.

## 3. Phase 4's porting surface grew — inventory of what ports how

Straight ports (platform-independent, copy + config-path edits only):
  routes (32 endpoints — note: may be split into blueprints by the debt
  session; port whatever structure exists at port time), db.py (10 tables +
  schema versioning if landed), insight.py, lookup.py (external APIs; .env
  loader carries over), all static/ JS+CSS, templates, tests, CI, training/.

Ports needing per-item attention:
  - **Segment overrides** call ffmpeg by argv — works identically on Windows;
    ship/locate ffmpeg.exe (winget install; document) and keep the
    soft-fail-when-absent behavior.
  - **waveform_cache / DAW waveforms**: pure numpy on decoded audio — but the
    44.1 kHz decode currently comes from Essentia MonoLoader. Native decode
    is ffmpeg -> float32 PCM (subprocess, s16le/f32le pipe) or soundfile;
    ONE decode helper feeds waveforms, key, and (resampled) the 16 kHz mel
    path. Oracle-check duration + a few waveform bins for sanity.
  - **/compare (MAEST second engine)**: defer to a late phase. Primary
    engine parity comes first; MAEST has official .onnx heads and the
    feature extractor may also ship .onnx by then — investigate when you
    get there, not before.
  - **/refine (fine hop)**: same embedder, smaller patch hop — make hop a
    parameter of the native frontend from day one (the plan already says
    this; reaffirming because refine ships in the app today).

## 4. Recommended sequencing (updated)

0. In Vibe_Identify FIRST: run the architectural-debt session (at minimum
   item 3, the analyze() decomposition). Its `_decode_and_infer` extraction
   creates the exact seam this project swaps — porting a decomposed
   analysis.py is surgical; porting the 150-line monolith is not.
1. Phase 0 unchanged: run tools/make_oracle.py on WSL against ~50 diverse
   tracks NOW, before any model or code drift. Copy oracle/ + the .pb/.zip
   models into this repo.
2. Sessions A–C per the plan (with §2's SavedModel/onnx-check updates).
3. Phase 4 per §3's inventory. Bring the tests and CI over with the code —
   they are most of the port's safety net.
4. Phase 5 per §1 (shell swap) + a requirements-windows.txt
   (onnxruntime-directml OR onnxruntime — never both) + optional PyInstaller.

## 5. Database continuity

Same schema -> the native app points GENRE_DB at the existing genre_v2.db
(now on the Windows filesystem side; note the file currently lives in the
WSL home dir — copy it out: \\wsl$\Ubuntu\home\<user>\genre_v2.db). Cache,
vibes, tags, training labels, segment overrides all carry over. Filepaths
stored as /mnt/c/... in old rows should be translated once by a small
migration (mnt-prefix -> drive letter) so audio preview and section
extraction keep working — add this as a numbered schema migration.

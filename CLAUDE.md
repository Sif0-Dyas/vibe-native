# Vibe Native

Local music-analysis desktop app: Flask API + ONNX Runtime engine (genre / BPM / key)
wrapped in a pywebview shell, packaged with PyInstaller + Inno Setup. Windows-only today.

## Commands

- Install: `pip install -e . -r requirements-dev.txt`
- Tests (fast, no models): `set FAKE_ANALYZER=1 && pytest -q`
- Tests (real engine, needs models in MODEL_DIR): `pytest -q`
- Lint + format: `ruff check . && ruff format --check .`
- SAST: `bandit -r src/vibenative/ -q`
- Run in browser: `python -m vibenative`
- Run desktop shell: `python desktop/genre_app.pyw`

## Layout

- `src/vibenative/` — engine (`analysis.py`, `onnx_engine.py`, `decode.py`, `tempo.py`, `key.py`), DB (`db.py`), routes in `routes/`
- `desktop/genre_app.pyw` — pywebview shell, per-launch auth token
- `src/vibenative/static/` + `templates/` — plain-JS frontend, no bundler
- `training/` — custom genre-head trainer (being ported to the ONNX engine)
- `tests/` — 480+ tests; `oracle/` holds the reference outputs the engine is validated against

## Hard rules

- No `essentia` imports anywhere, ever. `tests/test_no_essentia.py` enforces this once it exists.
- `db.py` migrations are append-only. Never edit a shipped migration; add a new numbered one.
- Any change to `decode.py`, `frontend_mel.py`, `tempo.py`, `key.py` or `onnx_engine.py` must keep
  `tests/test_oracle_match.py` green (or the plan says explicitly how to re-baseline it).
- Do not write user state next to the exe. Settings, taxonomy and snapshots belong under `%APPDATA%`.
- No new SQL in `routes/` — use the repository layer once it exists (Phase 3 of the plan).
- Never commit `models/*.onnx`, `data/enao.json`, `data/genres_electronic.json`, or `*.npz`.

## The remediation plan

`docs/REMEDIATION_PLAN.md` is the source of truth for what to work on and in what order.
Before starting a task, read the relevant phase. When an item is done: tests green, lint clean,
tick its checkbox in the plan, one commit per item, then stop and report before the next item.

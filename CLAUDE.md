# Vibe Native

Local music-analysis desktop app: Flask API + ONNX Runtime engine (genre / BPM / key)
wrapped in a pywebview shell, packaged with PyInstaller + Inno Setup. Windows-only today.

## Commands

- Install: `uv sync --group desktop` (deps in `pyproject.toml`, pinned in `uv.lock`; `uv lock` after editing deps)
- Tests (fast, no models): PowerShell `$env:FAKE_ANALYZER="1"; uv run pytest -q` · cmd `set "FAKE_ANALYZER=1" && uv run pytest -q`
  (the unquoted cmd form `set FAKE_ANALYZER=1 && ...` stores `"1 "` with a trailing space, which is not fake mode)
- Tests (real engine, needs the ONNX models in `models/`): `uv run pytest -q`
- Lint + format: `uv run ruff check . && uv run ruff format --check .`
- SAST: `uv run bandit -r src/vibenative/ -q`
- Pre-commit: `uv run pre-commit run --all-files` (ruff hooks run the locked ruff via `uv run`)
- Run in browser: `uv run python -m vibenative`
- Run desktop shell: `uv run python desktop/genre_app.pyw`

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
- Tests must never touch real user files. Before running any test that writes, confirm conftest sets
  VIBE_CONFIG_DIR, GENRE_DB and VIBE_TAXONOMY. Never run new tests against stashed or checked-out old
  code that predates a test's isolation — assert on the diff instead, or run the old code under the
  same env vars.

## The remediation plan

`docs/REMEDIATION_PLAN.md` is the source of truth for what to work on and in what order.
Before starting a task, read the relevant phase. When an item is done: tests green, lint clean,
tick its checkbox in the plan, one commit per item, then stop and report before the next item.

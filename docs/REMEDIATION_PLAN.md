# Vibe Native — Code Review & Remediation Plan (v2)

Reconciled 2026-09-24 against branch `clean-room/key-detector` @ `3fb029b`.
v1 (2026-09-23) was written against `main` @ `06fca49`, a month behind the branch.
Line numbers below are as of `3fb029b`; locate each site before editing rather than trusting the number.

## What the branch already did

These v1 findings are closed on the branch. Do not redo them.

| v1 item | Closed by | Notes |
| --- | --- | --- |
| Rewrite the AGPL `key.py` port | `f5d2a65`, `5106c01`, `c99511e` — `tonality.py` written from `docs/KEY_SPEC.md`, profiles trained on GiantSteps + Beatport | 66.6% on GiantSteps, ahead of the old detector. Remaining work is in Phase 4 |
| Third-party license inventory | `7ca0aaf` — `docs/PROVENANCE.md` | Supersedes v1 Section 2's layer table; this plan defers to it |
| mutagen (GPL-2.0) imported in-process | `8816620` — `metadata.py` reads tags with ffprobe | v1 missed this entirely. Verified on all 121 oracle tracks |
| CC BY-SA attribution reaches the user | `38a264b` — `notices.py`, Options tab | PROVENANCE #7 |
| WSL path handling scattered | `38a264b` — `legacy.py` | Routes still call it deliberately; see Legacy table |
| `/map` recomputed kNN + SVD + audit on every load | `65ac42d` — response cache in `routes/map.py:165` | `insight.audit()` still runs per rebuild, but only on invalidation |
| NUL byte in `app.js` | `3fb029b` | Pre-commit hook now refuses control bytes |
| `package.json` lint path pointed at a folder that didn't exist | on branch | |
| `key._spectral_peaks` reference implementation | gone with `key.py` | |
| Snapshots written next to the exe | on branch — `snapshots.py:40` now uses the DB's directory | Settings and taxonomy still have the problem |
| `tools/` had no index; build never proved the exe runs | `54a27f1` — `tools/README.md`, `tools/smoke_dist.py` | |

## Summary

The engine is shippable; the app around it is not, and the models it runs on cannot be sold under their current license. `docs/PROVENANCE.md` is the authoritative statement of the license position and is not repeated here. Reviewed: 26k lines across the Python engine, 79 Flask routes, the pywebview shell, ~7.5k lines of frontend JS, PyInstaller/Inno tooling and CI. Tests on the branch: 578 pass / 10 skip on Linux in FAKE mode (587 / 1 on Windows with models present).

What a release checklist stops on, in order:

1. **Licensing** — the MTG models (PROVENANCE #1–2). Everything else in Section 2 hangs off that decision.
2. **The installed build cannot write its own settings.** `settings.ini` and `taxonomy.json` live next to the exe in Program Files; the installer requires admin; the app runs as the user.
3. **The API is unauthenticated by default** and exposes copy-any-file and read-any-file primitives on form POSTs.
4. **No lockfile, and CI never runs the real product.** 26 files fail `ruff format --check` on the branch.
5. **DB access won't survive a 10k-track library** — every listing parses every full payload.

Nothing here is legal advice; the licensing items need counsel to confirm.

## Essentia removal — what is left

| Layer | Status | Remaining |
| --- | --- | --- |
| 1. Library imports | **open** | `analysis.py:67` (`get_maest`), `training/embed_extract.py:44` (`MonoLoader`). `tools/make_oracle.py` is a dev tool that legitimately needs Essentia; leave it, but it never ships |
| 2. Ported algorithm code | **mostly closed** | `key.py` is gone. `frontend_mel.py` / `tempo.py` frontends: PROVENANCE §3–4 argues they are parameter-matched textbook DSP, not ports — get counsel to confirm and then correct the README's AGPL claim. If counsel disagrees, re-derive from `librosa.filters.mel(htk=False, norm='slaney')` |
| 3. MTG models (CC BY-NC-ND) | **open, the blocker** | Per PROVENANCE §1–2: license from MTG/UPF, or replace with a permissive embedder (VGGish/YAMNet Apache-2.0, OpenL3 MIT, PANNs/CLAP — confirm weights) + a head trained on owned labels; tempo via `librosa.beat.tempo` (ISC). Verify every license yourself |
| 4. Key model training data | **open** | PROVENANCE #5: profiles are fitted on CC BY-SA annotations; retrain on the `key_labels` the app now collects |

Layer 1 actions:

- Delete `get_maest`, `maest_genre`, `MAEST_PB` (`analysis.py`), the `/compare` route (`routes/analysis.py:240`) with its MAEST branch and FAKE stub, the Compare panel in the frontend, `MAEST_MODEL` in `.env.example`, `models/discogs-maest-*.json`.
- Rewrite `training/embed_extract.py` to call `decode.decode_16k_mono` and `onnx_engine.get_engine()["embedder"]`. The training feature stays (decided 2026-09-23).
- Add `tests/test_no_essentia.py`: walk `src/`, `desktop/`, `training/`, fail on any `import essentia` / `from essentia`. Exclude `tools/make_oracle.py` by name.
- Move `requirements-convert.txt` and `tools/convert_models.py` under `tools/legacy/` until Layer 3 retires them.

CI guard: `pip-licenses --fail-on="AGPL;GPL;CC-BY-NC"` over the runtime venv, plus the import scan.

## Sale blockers

| # | Finding | Where | Fix |
| --- | --- | --- | --- |
| 1 | Models CC BY-NC-ND; `data/enao.json` (no stated license) ships **inside the exe** — PROVENANCE verified it in a real build | `Vibe Identify.spec:35` `collect_data_files("vibenative")` | Section 2; exclude `data/enao.json` from the spec now, settle it later (PROVENANCE #6) |
| 2 | Installed build writes to Program Files: `settings_ini()` and `taxonomy.path()` resolve next to the exe; installer is `PrivilegesRequired=admin`, `DefaultDirName={autopf}`; `/db-path` and every Genres-tab taxonomy edit fail for a normal user | `paths.py:26`, `taxonomy.py:35`, `tools/installer.iss:40,48` | Route both to `%APPDATA%\Vibe Identify\`; read the installer-written `settings.ini` as a one-time seed |
| 3 | No lockfile; `requirements.txt` unpinned; CI installs unpinned; pre-commit pins ruff 0.16.0 vs `>=0.6`; 26 files fail `ruff format --check` on the branch, so the pre-commit hook will block the next commit touching any of them | `requirements*.txt`, `ci.yml`, `.pre-commit-config.yaml` | One formatting-only commit first; then `uv lock` or `pip-compile --generate-hashes`; pin ruff in one place |
| 4 | CI never runs the product: `ubuntu-latest` only, no onnxruntime/ffmpeg/pywebview/models; engine modules excluded from coverage | `ci.yml:9`, `.coveragerc.ci` | Add a `windows-latest` job: `onnxruntime-directml` + ffmpeg, run `tools/smoke_dist.py` and the decode/import paths |
| 5 | Werkzeug dev server in production | `desktop/genre_app.pyw:322`, `__main__.py:47` | `waitress.serve(app, host="127.0.0.1", port=PORT)` |

Also: code signing; `oracle/index.json` publishes your Windows username and 121 personal track filenames — reduce to hashes.

## Security

| Finding | Where | Fix |
| --- | --- | --- |
| Auth is opt-in: `_loopback_guard` only runs when `GENRE_TOKEN` is set; `python -m vibenative` has no token and no DNS-rebinding defence | `routes/_shared.py:21` | Make the token mandatory; print the `?k=` URL at startup |
| Copy-any-file: `/save_training` copies any server path the form names into `~/genre_training/` | `routes/training.py:39` | JSON bodies only (a form POST needs no CORS preflight), check `Origin`, accept only paths already in `tracks.filepath` |
| Read-any-file: `/compare` decodes any `filepath`; `/batch` walks any directory | `routes/analysis.py:240`, `:553` | `/compare` goes away; `/batch` keeps an allow-list of roots picked through the native dialog |
| Browser filename used as a path: `Path(f.filename).name` | `routes/training.py` upload branch | `werkzeug.utils.secure_filename` (0 uses today) |
| Discogs token/key/secret sent as query params | `lookup.py:55-60, 93-96` | `Authorization: Discogs token=…` header; never log the URL |
| `/reveal` spawns `explorer` unconditionally (now has `timeout=10`) | `routes/library.py:172` | Gate on `sys.platform` |

XSS: `escapeHtml` is applied consistently; no finding. The pywebview JS API exposes only `pick_folder`.

## Correctness bugs

| Bug | Where | Fix |
| --- | --- | --- |
| `get_maest()` imports `essentia.standard` → 500 from `/compare` for anyone with the `.pb` present | `analysis.py:67` | Delete (Section 2) |
| `/batch` cannot be cancelled: all futures submitted up front; on disconnect `ThreadPoolExecutor.__exit__` waits for every one; client hardcodes `workers: 3`, no abort UI | `routes/analysis.py` `analyze_one` block, `app.js` batch fetch | Cancel `Event`, lazy submit, `shutdown(cancel_futures=True)`; `AbortController` + Cancel button |
| Three answers to "what genre is this track": `_shared._dominant_style`, `insight.dominant`, `/library` raw `styles[0]` — Library tab ignores an override the Map honours | `routes/_shared.py:63`, `insight.py:46`, `routes/library.py:71` | One `dominant_style()` in a domain module |
| `onnx_engine.get_engine()` has no build lock; `tempo._session()` does → a cold 3-worker batch builds three engines | `onnx_engine.py` `get_engine` | Same double-checked lock as `tempo`, or build eagerly at app start |
| `tempo.PROVIDER_ORDER` is DML-first while `onnx_engine` defaults to CPU because DML faults the driver | `tempo.py:30`, `onnx_engine.py:59` | One provider policy in `onnx_engine`, imported by `tempo` |
| `/forget` deletes from `tracks`, `track_tags`, `vibe_tracks`, `segment_overrides` only | `routes/library.py:31-34` | Also `lookup_cache`, `waveform_cache`, `ratings`, `training_labels`, `training_rejects`, **`key_labels`** (new on this branch) |
| `neighbor_check` computed in `analyze_route` only, never in `analyze_one` | `routes/analysis.py:115` vs `:574` | One shared `analyze_and_store()` |
| ffmpeg/ffprobe `subprocess.run` with no `timeout` — `decode.py` (both calls) and `metadata.py:53` | | `timeout=120`; treat expiry as a per-file failure |
| `cache_put` positional `INSERT … VALUES(?,?,?,?,?,?,?)` | `db.py:308` | Name the columns |
| FAKE `bpm_confidence` on the 0.5–5.0 scale; real is 0–1 | `analysis.py:511` | Emit 0–1 |
| `/db-path` writes a setting the running process can't honour (`DB_PATH` is import-time) and writes it to Program Files | `db.py:44`, `routes/library.py` | Goes away with the config object + blocker #2 |

## Performance at 10k tracks

**Decode memory** (the batch OOM `_rss_mb` was added for): `decode_mono` holds the file as float64, decoded twice per track — 16 kHz (`analysis.py:339`) and 44.1 kHz (`:346`) — across 3 workers. Fix, oracle-safe: one ffmpeg call at native rate with `-af "pan=mono|c0=0.5*c0+0.5*c1"` (the same amplitude-average mix as the numpy code), float32, resample twice from that buffer. Re-run `tests/test_oracle_match.py`; then delete `_rss_mb`.

**Full-payload parsing on read paths.** `/library` (9 `json.loads` sites in `routes/library.py`), `/similar`, `/training/candidates`, `insight.check` on every drop — each parses every stored payload to read six scalars. Add denormalized columns (`style`, `bpm`, `key`, `scale`, `camelot`, `duration`) in a migration, or `json_extract`.

**One global DB lock** plus a new connection per call serializes every operation process-wide. With WAL, use a thread-local connection. **Zero indexes** in `db.py`: add `vibe_tracks(hash)`, `track_tags(hash)`, `training_labels(hash, genre)`, `segment_overrides(hash)`, `key_labels(hash)`.

**Network fonts in a desktop app** (`index.html`, 2 Google Fonts links): bundle the woff2 files.

## Maintainability

1. **Config as an object.** `config.py` (8 env reads at import), `db.DB_PATH`, `_shared._AUTH_TOKEN`, `onnx_engine.MODELS`, `tempo.MODELS`. The per-test module-reload hack in `tests/conftest.py` exists only because of this. `Settings` dataclass → `create_app(settings)` → `app.config`.
2. **Repository layer.** Raw SQL executes per route module: `vibes.py` 21, `library.py` 20, `training.py` 9, `analysis.py` 7, `playlists.py` 7, `tags.py` 7. `vibenative/repo/` with typed functions; routes contain no SQL.
3. **One `dominant_style()`.**
4. **One taxonomy.** Six sources: `keystone.py`, `taxonomy.py`, `genrelex.py`, `enao.py`, `static/genre_families.json` (read by `insight.py` *and* the frontend), `genres.py` PROFILES.
5. **Dedupe.** Genre→folder sanitizer ×9 and `~/genre_training` ×7 while `trainsets._safe` / `trainsets.ROOT` exist; two mel filterbanks; identical try/except per route → one `@bp.errorhandler`; 21 function-local `import numpy` — the Essentia lazy-import rationale is gone.
6. **Layering.** `trainsets.py:75` imports from `routes._shared`; `routes/analysis.py` imports `_lock` from `analysis`.
7. **Extract FAKE mode** (8 `FAKE` sites in `analysis.py`, 6 in `routes/analysis.py`) into `fake_engine.py` behind the engine contract.
8. **Frontend as ES modules.** 12 `<script>` tags, zero `type="module"`, a hand-maintained 43-entry globals list in `eslint.config.js`.
9. **One name, one version.** "Vibedentify" in 11 files including `index.html`, `lookup.py:25`, four JS files; version duplicated in `pyproject.toml:7` and `__init__.py:14`. `/api/v1` prefix; DELETE verbs.
10. **Windows-isms** → `platform.py` (post-release, decided).

## Legacy code to remove

| Group | Delete | Keep / replace with |
| --- | --- | --- |
| MAEST | `get_maest`, `maest_genre`, `MAEST_PB`; `/compare` + Compare panel; `MAEST_MODEL`; `models/discogs-maest-*.json` | Nothing — decided 2026-09-23 |
| Essentia-era config | `MODEL_DIR` default `~/essentia_models`; `CUSTOM_HEAD` default there; `.env.example` `*.pb` lines | `%APPDATA%\Vibe Identify\models\` |
| Custom-head trainer | `training/embed_extract.py:44` Essentia import | Port to `onnx_engine`. Feature stays (decided) |
| WSL legacy | `tools/db_cutover.py`, `tools/make_oracle.py`; `legacy.py` and its 4 route call sites (`routes/analysis.py:550`, `routes/library.py:574, 597`); the "no WSL" selftest assertions | Already isolated in `legacy.py` by design — delete in one piece once no install needs it. `_migration_2` keeps its own copy of the path rewrite |
| Desktop two-process mode | `GENRE_DESKTOP_MULTIPROC`, `venv_python`, `start_backend`, `_shutdown_backend`, `backend_cmd/env`, `WIN_PROJECT`, `_LAUNCH_WARNING`; both `.bat` launchers; `_selftest` | Single-process only; selftest → `tests/test_desktop_shell.py` |
| Waveform | `waveform_peaks` 720-bin envelope (`analysis.py:184`) — pre-load fallback for the cached 1600-bin `wave` | Drop if the DAW waveform is always cached at analysis |
| Narration | 12 "Phase N" docstring refs; `onnx_engine.py` header still says `embedder()` raises `NotImplementedError`; README still says DirectML is the default (`onnx_engine.py:59` says CPU); `docs/history/` | |
| Identity | `lookup.USER_AGENT` = `Vibedentify/1.0 (+…/Vibe_Identify)` | `__version__` + this repo |
| Diagnostics | `_rss_mb` | After the decode-once fix |
| Fixtures | `oracle/index.json` user paths | Hashes |
| Requirements | `pywebview` in two files; `pytest` in `requirements.txt` | One runtime, one dev, one lock |

## Order of work

**Phase 0 — same day, no design decisions**

- [x] Fix the NUL byte in `app.js`; control-character pre-commit check — `3fb029b`
- [x] Formatting-only commit: `ruff format .`, nothing else, so the pre-commit hook stops blocking real commits
- [x] Delete MAEST and the `/compare` route + Compare panel
- [x] `tests/test_no_essentia.py`
- [x] Port `training/embed_extract.py` to `decode` + `onnx_engine`
- [x] `timeout=120` on both `decode.py` calls and `metadata.py:53`
- [x] `tempo.py` imports `PROVIDER_ORDER` from `onnx_engine`
- [ ] Double-checked build lock in `onnx_engine.get_engine()`
- [ ] `/forget` deletes from all ten tables (incl. `key_labels`)
- [ ] Name the columns in `db.cache_put`
- [ ] Exclude `data/enao.json` from the PyInstaller spec
- [ ] Lockfile; pin ruff once; CI installs from the lock

**Phase 1 — user-visible failures**

- [ ] `settings.ini` and `taxonomy.json` to `%APPDATA%\Vibe Identify\`; seed once from the installer-written file
- [ ] `GENRE_TOKEN` mandatory; print the `?k=` URL in `__main__`
- [ ] JSON-only bodies + `Origin` check on mutating routes; `secure_filename`; `/save_training` accepts only known `tracks.filepath`
- [ ] Discogs credentials to the `Authorization` header
- [ ] Cancellable `/batch` + Cancel button
- [ ] waitress in `genre_app.pyw` and `__main__.py`

**Phase 2 — engine and data paths (re-run the oracle gate after)**

- [ ] Decode once per track; remove `_rss_mb`
- [ ] Denormalized columns via a new migration; rewrite `/library`, `/similar`, `/training/candidates`
- [ ] Indexes
- [ ] Thread-local connections; retire `_db_lock` for reads

**Phase 3 — structure (one PR each, in this order)**

- [ ] `Settings` object; delete the conftest reload hack
- [ ] Repository layer; routes contain no SQL
- [ ] One `dominant_style()`; one `@bp.errorhandler`; `trainsets` stops importing from `routes`
- [ ] `fake_engine.py`; FAKE branches out of routes and `analysis.py`
- [ ] Dedupe sanitizer / training root / mel filterbank; drop the 21 lazy numpy imports
- [ ] `taxonomy/` package
- [ ] Frontend to ES modules
- [ ] `/api/v1`; DELETE verbs; one name; one version source

**Phase 4 — the license work (parallel with Phase 1; gates any sale)**

- [x] Clean-room key detector — `tonality.py`, `KEY_SPEC.md`
- [x] Third-party inventory — `PROVENANCE.md`; in-app notices
- [x] Drop mutagen (GPL) — `metadata.py`
- [ ] Ask MTG/UPF about a commercial license for the models — the answer decides the rest
- [ ] Accuracy benchmark: hand-label ~200 tracks from the library (genre, BPM, key) alongside GiantSteps; every engine change reports against it. Current key baseline: 66.6% GiantSteps
- [ ] Retrain key profiles on owned `key_labels` (PROVENANCE #5)
- [ ] Counsel confirms `frontend_mel.py` / `tempo.py` provenance (PROVENANCE §3–4); fix the README's AGPL claim accordingly
- [ ] Settle `enao.json` (PROVENANCE #6): permission, replacement, or stop shipping
- [ ] If no license: permissive embedder + tempo estimator; retrain the genre head on the 400-label taxonomy; retire `tools/convert_models.py`, `requirements-convert.txt`
- [ ] `pip-licenses --fail-on` in CI

**Phase 5 — proving it**

- [ ] `windows-latest` CI job running `tools/smoke_dist.py`
- [ ] Code signing
- [ ] Remaining Legacy table rows; `docs/history/`

**Post-release**

- [ ] `platform.py`; macOS port; ensemble only if a licensed second model exists

**Decisions (2026-09-23)**

- Custom-head training is critical: stays, ported in Phase 0.
- `/compare` is removed with MAEST; accuracy is pursued through the Phase 4 benchmark.
- macOS is post-release.
- Work lands on `clean-room/key-detector`; `main` is a month stale and gets a merge when Phase 0 is done.

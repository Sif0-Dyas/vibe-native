# Vibe Native — Code Review & Remediation Plan

As of 2026-09-23 · reviewed at `main` 06fca49

## Summary

The engine is shippable; the app around it is not, and the models it runs on cannot be sold at all under their current license. Reviewed at `main` (06fca49, 2026-08-26): 26k lines across the Python engine, 79 Flask routes, the pywebview shell, ~7.5k lines of frontend JS, PyInstaller/Inno tooling and CI.

What holds up: the ONNX engine is oracle-validated (genre cosine > 0.999, key 121/121), migrations are append-only, the desktop shell's per-launch token is the right design, and the test suite is real — 482 pass in 8.4s on Linux in FAKE mode. Bandit is clean.

What a release checklist stops on, in order:

1. **Licensing.** Genre and tempo models are MTG's under CC BY-NC-ND; `key.py` and parts of `frontend_mel.py` are Essentia (AGPL-3.0) ports; the build bundles crawled data the repo says must never be redistributed. Section 2 is the removal plan.
2. **The installed build cannot write its own settings.** `settings.ini` and `taxonomy.json` live next to the exe in Program Files; the installer requires admin; the app runs as the user.
3. **The API is unauthenticated by default** and exposes copy-any-file and read-any-file primitives on form POSTs.
4. **No lockfile, and CI never runs the real product.** `ruff format --check` already fails on current ruff (0.16.8).
5. **DB access won't survive a 10k-track library** — every listing parses every full payload; every map load recomputes two kNN passes.

Every finding below carries a `file:line` so it can be handed to Claude Code as-is. Nothing here is legal advice; the licensing items need counsel to confirm.

## Essentia removal plan

"Remove Essentia" is three separate jobs of very different size, and only the third one clears a commercial path. Removing the library imports is an afternoon; rewriting the ported algorithms is a week; replacing the MTG models is the actual project.

| Layer | What depends on it today | Action | Effort |
| --- | --- | --- | --- |
| 1. Library imports | `analysis.py:67` (`essentia.standard.TensorflowPredictMAEST`), `training/embed_extract.py:44` (`MonoLoader`) | Delete MAEST; port `embed_extract` to `vibenative.decode` + `onnx_engine` | Hours |
| 2. Ported algorithm code (AGPL-3.0 per README) | `key.py` (PeakDetection, SpectralWhitening, HPCP, Key — "verbatim from the algorithm source"), `frontend_mel.py` and `tempo._melspectrogram` ("matching Essentia's frontend") | Re-implement key detection from published papers on librosa/scipy; re-derive both mel frontends from the librosa/Slaney definition; strip the "ported from Essentia" provenance | About a week |
| 3. MTG models (CC BY-NC-ND) | Discogs-EffNet embedder, `genre_discogs400` head, TempoCNN `deeptemp-k16`, MAEST; every `models/*.json`; `tools/convert_models.py`; the `oracle/` fixtures; the custom head trained on EffNet embeddings | Either a commercial license from MTG/UPF, or new models on a permissively licensed backbone | Weeks to months |

### Layer 1 — imports (do first, trivially safe)

- Delete `get_maest`, `maest_genre`, `MAEST_PB` (`analysis.py:48-87`), the MAEST branch of `compare_engines` (`routes/analysis.py:180-219`) and its FAKE stub that reports `maest_available: true`, and `MAEST_MODEL` from `.env.example`. `/compare` goes with it: without a second model there is nothing to compare.
- Rewrite `training/embed_extract.py` to call `decode.decode_16k_mono` and `onnx_engine.get_engine()["embedder"]` — the embedder it needs already exists in the app.
- Add `tests/test_no_essentia.py`: walk `src/`, `desktop/`, `tools/`, `training/` and fail on any `import essentia` / `from essentia`. This is the guard that keeps it gone.
- Retire `requirements-convert.txt` (tensorflow, tf2onnx) and `tools/convert_models.py` once Layer 3 lands; until then move them under `tools/legacy/` so nobody installs 500 MB of TensorFlow by accident.

### Layer 2 — the ported algorithms

`key.py` is the clear case: its docstring says each stage is ported verbatim from `peakdetection.cpp`, `spectralwhitening.cpp`, `hpcp.cpp` and `key.cpp`. Replace it with a new module written from the literature, not from the existing file:

- Chroma from `librosa.feature.chroma_cqt` (ISC license) or a scipy STFT + pitch-class fold, averaged over the track.
- Key by correlating the mean chroma against published profiles at 12 rotations: Krumhansl–Kessler (1982) or Temperley (1999) are fully documented in their papers. The `bgate` numbers in `key.py:59-60` came into the file via Essentia's source; source them from Faraldo's published work or drop them.
- Expect a lower oracle match than 121/121 — the oracle *is* Essentia. Re-baseline: accept ≥ 90% agreement on the 121 tracks and keep the mismatches as a review list, or build a new reference set from Rekordbox/Mixed In Key readings of the same tracks.

`frontend_mel.py` and `tempo._melspectrogram` are generic DSP (symmetric Hann, power STFT, Slaney mel filterbank, `log10(1 + 10000·x)`), and their docstrings cite Essentia mainly for parameter values. The safe move is still to re-derive them from librosa's definitions (`librosa.filters.mel(htk=False, norm='slaney')`, `window=scipy.signal.windows.hann(512, sym=True)`), delete the duplicate filterbank in `tempo.py:163-185`, and have counsel confirm the provenance note in the README can go.

`decode.py` is original numpy that reproduces MonoLoader's behaviour (amplitude-average mix, linear resample with a calibrated phase). Reproducing behaviour is not derivation; keep it, but drop the "matching Essentia" framing once the oracle is retired.

### Layer 3 — the models

This is what the product actually runs on, and CC BY-NC-ND forbids both commercial use and derivatives (the ONNX conversion is arguably a derivative). Two paths:

1. **License them.** MTG/UPF offers commercial licensing for Essentia and its models; ask before building anything. If granted, Layers 1–2 still apply to the code.
2. **Replace them.** Train the genre head on a permissively licensed embedder and swap the tempo model for a permissive estimator. Verify each license yourself before committing — candidates:
   - Embedders: VGGish / YAMNet (Apache-2.0, Google), OpenL3 (MIT), PANNs (code MIT; confirm weights), LAION CLAP (Apache-2.0 code; confirm weights). MERT and madmom's models are non-commercial — skip them.
   - Tempo: `librosa.beat.tempo` / `beat_track` (ISC). For steady four-on-the-floor material it holds up; validate against the 121-track set and accept the 2%-or-octave rule.
   - Labels: Discogs' genre/style names are a vocabulary, not a model; keep the 400-label taxonomy and retrain the head on it with your own labelled library plus the `~/genre_training` folders (once Layer 1 makes the trainer runnable).

After Layer 3 the `oracle/` folder becomes a benchmark, not a gate: compare the new stack against it to catch regressions in *behaviour*, never expect numeric equality.

### CI guard

Add a license check to the pipeline so this cannot regress silently: `pip-licenses --fail-on="AGPL;GPL;CC-BY-NC"` over the runtime venv, plus the `test_no_essentia.py` import scan.

## Sale blockers

Five items a release manager would refuse to sign off on, independent of code quality.

| # | Finding | Where | Fix |
| --- | --- | --- | --- |
| 1 | Models CC BY-NC-ND; `key.py`/`frontend_mel.py` AGPL ports; `Vibe Identify.spec` uses `collect_data_files("vibenative")`, so `data/enao.json` and `data/genres_electronic.json` get bundled whenever they exist on the build machine despite `.gitignore` saying "never redistributed" | README §License, `Vibe Identify.spec:27`, `.gitignore` | Section 2; add an explicit exclude for `data/` in the spec until the data licensing is settled |
| 2 | Installed build writes to Program Files: `settings_ini()` and `taxonomy.path()` resolve next to the exe; installer is `PrivilegesRequired=admin`, `DefaultDirName={autopf}`; the app runs unelevated, so `/db-path` and every Genres-tab taxonomy edit fail with a permission error | `paths.py:37-39`, `taxonomy.py:62`, `snapshots.py:39`, `tools/installer.iss:40,48` | Route settings, taxonomy and snapshots to `%APPDATA%\Vibe Identify\` (the log already goes to `%LOCALAPPDATA%`); read the installer-written `settings.ini` as a one-time seed |
| 3 | No lockfile: `requirements.txt` unpinned; CI installs unpinned; `pip-audit` audits today's resolution, not the shipped one; pre-commit pins ruff 0.16.0 vs `>=0.6` in requirements; `ruff format --check` fails on ruff 0.16.8 (`palettes.py:280`) | `requirements*.txt`, `ci.yml:22`, `.pre-commit-config.yaml` | `uv lock` or `pip-compile --generate-hashes`; install from the lock everywhere; pin ruff in one place |
| 4 | CI never runs the product: Windows-only app tested on `ubuntu-latest` with no onnxruntime, ffmpeg, pywebview or models; engine modules excluded from coverage | `ci.yml`, `.coveragerc.ci` | Add a `windows-latest` job: `onnxruntime-directml` + ffmpeg via winget/choco, run decode and import paths, a small stand-in ONNX model for the engine smoke test |
| 5 | Werkzeug dev server in production, in-process, `threaded=True` | `desktop/genre_app.pyw:344`, `__main__.py:47` | `waitress.serve(app, host="127.0.0.1", port=PORT)` — `wsgi.py` already names it |

Also on the list: code signing (README acknowledges the SmartScreen prompt), and `oracle/index.json` publishes your Windows username and 121 personal track filenames in a public repo — reduce to hashes.

## Security

Threat model for a sold desktop app: a hostile web page open in the same browser, a hostile audio file with crafted tags, and another local process. Today the first two are wide open in browser mode.

| Finding | Where | Fix |
| --- | --- | --- |
| Auth is opt-in: `_loopback_guard` only runs when `GENRE_TOKEN` is set, so `python -m vibenative` and the README's browser workflow have no token and no DNS-rebinding defence | `routes/_shared.py:21-35` | Make the token mandatory; print the `?k=` URL at startup; keep the desktop shell's per-launch generation |
| Copy-any-file: `/save_training` copies whatever server path the form names into `~/genre_training/` | `routes/training.py:39-48` | Require JSON bodies (no form encoding — a form POST needs no CORS preflight), check `Origin`, and only accept paths already recorded in `tracks.filepath` |
| Read-any-file: `/compare` decodes any `filepath`; `/batch` walks any directory | `routes/analysis.py:243-249, 456-457` | Same: token + JSON + `Origin`; for `/batch` keep an allow-list of roots the user picked through the native dialog |
| Browser filename used as a path: `Path(f.filename).name` — safe on Windows only; on the planned macOS port backslashes are not separators | `routes/training.py:54` | `werkzeug.utils.secure_filename` |
| Discogs token/key/secret in the query string, and the failure path logs the exception | `lookup.py:96-110` | `Authorization: Discogs token=…` header; never log the URL |
| `/reveal` spawns `explorer` unconditionally | `routes/library.py:136` | Gate on `sys.platform`; `open -R` on macOS |
| `/clientlog` lets any local caller write to the app log at chosen level | `routes/analysis.py:416-427` | Fine once the token is mandatory; keep the 2000-char cap |

XSS review: `escapeHtml` is applied consistently where tag data reaches `innerHTML` (checked `app.js`, `panels.js`, `map.js`); no finding there. The pywebview JS API only exposes `pick_folder`, which needs user interaction — low value to an attacker.

## Correctness bugs

Twelve confirmed defects, ordered by user impact.

| Bug | Where | Effect | Fix |
| --- | --- | --- | --- |
| `get_maest()` imports `essentia.standard` | `analysis.py:67` | Any user who migrated with the `.pb` in `~/essentia_models` gets a 500 from `/compare` | Delete (Section 2, Layer 1) |
| `/batch` cannot be cancelled: all futures submitted up front; on client disconnect the generator closes and `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`, so the scan runs to the end invisibly. Client hardcodes `workers: 3` with no abort UI | `routes/analysis.py:525-531`, `app.js:1328-1331` | Closing the tab does not stop a 5,000-file scan | A job object with a cancel `Event`; submit lazily; `shutdown(cancel_futures=True)`; an `AbortController` and a Cancel button on the client |
| Three answers to "what genre is this track": `_shared._dominant_style` (5 tiers), `insight.dominant` (ignores weights and relabel), `/library` reads raw `styles[0]` | `routes/_shared.py:63-103`, `insight.py:46-56`, `routes/library.py:49` | The Library tab shows the model's read after a manual override that the Map honours | One `dominant_style()` in a domain module, used everywhere |
| `onnx_engine.get_engine()` has no build lock; `tempo._session()` does | `onnx_engine.py:84-87` vs `tempo.py:211-227` | A cold `/batch` with 3 workers builds three EffNet engines at once (2 sessions each) | Same double-checked lock as `tempo`, or build eagerly at app start |
| `tempo.PROVIDER_ORDER` is DML-first while `onnx_engine` defaults to CPU because DML faults the NVIDIA driver | `tempo.py:160`, `onnx_engine.py:59-63` | TempoCNN still runs on the path you disabled; `VIBE_PROVIDER` is ignored by it | One provider policy in `onnx_engine`, imported by `tempo` |
| `/forget` deletes from `tracks`, `track_tags`, `vibe_tracks` only | `routes/library.py:22-25` | Orphans in `segment_overrides`, `lookup_cache`, `waveform_cache`, `ratings`, `training_labels`, `training_rejects` (no FKs) | Delete from all seven, or add `FOREIGN KEY … ON DELETE CASCADE` in a migration |
| `app.js` contains a literal NUL byte at offset 14220 (`'ovr\x00' + ov.genre`) | `app.js` inside `drawSegments` | git and grep treat your largest file as binary — no diffs, no code search | Replace with the intended separator; add a pre-commit check for control characters |
| `neighbor_check` computed for drop-analyzed tracks only | `routes/analysis.py:97-99` vs `analyze_one` | Batch-scanned tracks never get the misread flag at analysis time | Call `insight.check` from one shared `analyze_and_store()` |
| ffmpeg/ffprobe `subprocess.run` with no `timeout` | `decode.py:240, 282` | One hung decode on a corrupt file pins a worker forever | `timeout=120`; treat expiry as a per-file failure |
| `cache_put` uses a positional `INSERT … VALUES(?,?,?,?,?,?,?)` | `db.py:224` | The next `tracks` column breaks every write | Name the columns |
| FAKE `bpm_confidence` still on the 0.5–5.0 Essentia scale; real is 0–1 | `analysis.py:564` | FAKE mode lies about the contract the UI thresholds on | Emit 0–1 |
| `/db-path` writes a setting the running process can't honour (`DB_PATH` is an import-time constant) | `routes/library.py:144-192`, `db.py:44` | Restart required, and the file it writes lands in Program Files (Section 3, #2) | Goes away with the config object (Section 7) |

## Performance at 10k tracks

The batch OOM you instrumented `_rss_mb` for has a single cause, and the read paths degrade linearly with library size because every listing re-parses every full payload.

**Decode memory.** `decode_mono` holds the whole file as float64, and each track is decoded twice (16 kHz for genre, 44.1 kHz for tempo/key) across 3 workers (`decode.py:275-290`, `analysis.py:392-399`). A 10-minute 48 kHz stereo file peaks near 1 GB per decode; three workers give a multi-GB spike. Fix, oracle-safe:

- One ffmpeg call per track at native rate with `-af "pan=mono|c0=0.5*c0+0.5*c1"` — exactly the amplitude-average mix `decode.py` does in numpy today, so the stereo buffer never exists in Python.
- Keep float32 throughout; the linear resample differs at the 1e-7 level, far under the 0.999 cosine gate.
- Resample to 16 kHz and 44.1 kHz from that one buffer. Subprocess count per track drops from 4 to 2 (probe + decode).
- Re-run `tests/test_oracle_match.py` after; if cosine holds you also remove `_rss_mb` (`routes/analysis.py:376-413`).

**Full-payload parsing on read paths.** `/library` (`routes/library.py:34-59`), `/similar` (`:449-482`), `/training/candidates` (`routes/training.py:107-160`), and `insight.check` on every drop (`insight.py:88-110`) each `json.loads` every stored payload — 720 waveform floats, frames and segments included — to read six scalars. Add denormalized columns (`style`, `bpm`, `key`, `scale`, `camelot`, `duration`) in a migration, or select with `json_extract(payload, '$.bpm')`.

**Map recompute.** `/map` (`routes/map.py:124-206`) runs a blocked kNN, an SVD and `insight.audit()` — a second full kNN — on every load. Cache the node list, edges and flags keyed on `(COUNT(*), MAX(created))`; invalidate on write.

**One global DB lock.** `_db_lock` plus a fresh `sqlite3.connect` per call (`db.py:45-52`) serializes every read and write process-wide across 15 modules. With WAL on, readers don't block writers; use a thread-local connection and let SQLite lock. Add indexes on `vibe_tracks(hash)`, `track_tags(hash)`, `training_labels(hash, genre)`, `segment_overrides(hash)`.

**Network fonts in a desktop app.** `index.html:7-8` loads Syne, JetBrains Mono and DM Sans from Google Fonts: an offline start renders in fallback fonts and every launch pings Google. Bundle the woff2 files under `static/fonts/`.

## Maintainability

Ten structural changes; the first two unlock most of the others.

1. **Config as an object, not import-time globals.** `config.py`, `db.DB_PATH` (`db.py:44`), `_shared._AUTH_TOKEN` (`:21`), `onnx_engine.MODELS` (`:35`), `tempo.MODELS` (`:152`) all read the environment at import. The test fixture's "delete every `vibenative.*` module and reimport per test" hack (`tests/conftest.py:38-41`) exists only because of this. Build a `Settings` dataclass once, pass it to `create_app(settings)`, and store it on `app.config`.
2. **A repository layer.** 15 modules open `with _db_lock, closing(db()) as conn, conn as c` and run raw SQL (19 executes in `routes/vibes.py`, 19 in `routes/library.py`, 9 in `routes/training.py`). A `repo/tracks.py`, `repo/vibes.py`, `repo/training.py` with typed functions makes the `/forget` orphan bug and the positional-INSERT bug one-line fixes, and makes the lock an internal detail.
3. **One `dominant_style()`** shared by `/library`, `/map`, `/similar` and `insight` (Section 5).
4. **One taxonomy.** Genre knowledge lives in six places: `keystone.py` tables, `taxonomy.py` overlay, `genrelex.py`, `enao.py`, `static/genre_families.json` (read by both `insight.py:34` and the frontend), `genres.py` PROFILES — plus hardcoded genre lists in the FAKE code. Consolidate into a `taxonomy/` package with one resolver and one JSON endpoint the frontend fetches.
5. **Kill the duplication.** The genre→folder sanitizer is copied 9 times and `Path.home() / "genre_training"` 7 times while `trainsets._safe` and `trainsets.ROOT` already exist. Two mel-filterbank implementations (`frontend_mel.py:67`, `tempo.py:163`). Every route repeats the same `try/except UploadError/Exception` — one `@bp.errorhandler`. 19 function-local `import numpy` calls: numpy is a hard dependency; the Essentia rationale for lazy imports is gone.
6. **Fix the layering.** `trainsets.py` imports from `routes._shared`; `routes/analysis.py` imports `_lock` from `analysis`. Domain helpers move out of the HTTP package; the inference lock hides inside the engine.
7. **Extract FAKE mode.** About 120 lines of fake-data generation sit inside `analyze()` (`analysis.py:496-573`), `refine_route` (`routes/analysis.py:119-152`) and `compare_route` (`:227-241`). A `fake_engine.py` implementing the same `{labels, embedder, classifier}` contract as `onnx_engine` lets the routes stop knowing.
8. **Frontend as ES modules.** 7.5k lines across 10 scripts share one global scope; `eslint.config.js` hand-maintains the cross-file globals list; `map.js` is 2,020 lines and `app.js` 1,597. `<script type="module">` works in WebView2 with no bundler, and the globals list disappears with it.
9. **One name, one version, one API prefix.** vibenative / Vibedentify / Vibe Identify / vibedentify-frontend coexist across `pyproject.toml`, `index.html:6`, `lookup.py:25`, `package.json`; `package.json`'s lint path (`vibedentify/static/`) doesn't exist; the version lives in both `pyproject.toml` and `__init__.py:14`. Routes mix pages and API with POST-for-delete (`/playlists/<id>/delete`, `/forget/<h>`, `/override_segment/delete`) — put a versioned `/api/v1` contract in before anything integrates.
10. **Collect the Windows-isms.** `_rss_mb` ctypes in a route module, `explorer` in `/reveal`, `CREATE_NO_WINDOW`, the WinGet Links lookup in `decode._tool` — one `platform.py` before the macOS port starts.

## Legacy code to remove

Everything below is either dead on the native build or exists only to bridge from the WSL app; none of it is used by an installed copy.

| Group | Delete | Keep / replace with |
| --- | --- | --- |
| MAEST | `get_maest`, `maest_genre`, `MAEST_PB` (`analysis.py:48-87`); MAEST branch of `compare_engines` and its FAKE stub (`routes/analysis.py:180-241`); `MAEST_MODEL` in `.env.example`; `models/discogs-maest-*.json` | Drop the route and the Compare panel: without a second model there is nothing to compare. Accuracy becomes a measured target in Phase 4. |
| Essentia-era config | `MODEL_DIR` default `~/essentia_models` (`config.py:59`); `CUSTOM_HEAD` default there (`analysis.py:91`); `.env.example` lines about `*.pb` and "Essentia model files" | `%APPDATA%\Vibe Identify\models\` for user extras |
| Custom-head trainer | `training/embed_extract.py` imports `essentia.standard` (`:44`) — so `/override`, `/save_training`, `/training/*`, `custom_predict`, `relabel.py` and the snapshot handling of the head all feed a trainer that cannot run natively | Port `embed_extract.py` to `onnx_engine` (small — the embedder exists) **or** remove the feature and its UI. Decided 2026-09-23: it is critical, so port it — the second option is off the table |
| WSL migration | `tools/db_cutover.py`, `tools/make_oracle.py`; `wsl_to_windows()` calls in `/batch` (`routes/analysis.py:457`) and `/filepaths/*` (`routes/library.py:510, 532`); the `paths.py` docstring; the "no WSL anywhere" selftest assertions (`genre_app.pyw:626-628`) | `wsl_to_windows` stays only inside `_migration_2` — shipped migrations are append-only |
| Desktop two-process mode | `GENRE_DESKTOP_MULTIPROC`, `venv_python`, `start_backend`, `_shutdown_backend`, `backend_cmd`, `backend_env`, `WIN_PROJECT`, `_LAUNCH_WARNING` (`genre_app.pyw:59-63, 129-243`); both `.bat` launchers; `_selftest` (`:571-641`) | Single-process only; the selftest checks become `tests/test_desktop_shell.py` |
| Reference implementations | `key._spectral_peaks` (`key.py:118-173`, the slow reference) — moot once Layer 2 rewrites the module | Delete with `key.py` |
| Waveform | `waveform_peaks` 720-bin envelope (`analysis.py:237-251`) is now only the pre-load fallback for the cached 1600-bin `wave` | Decide whether 720 floats per payload still earn their place; if the DAW waveform is always cached at analysis time, drop it |
| Narration | 13 "Phase N" docstring references; `onnx_engine.py:16-19` still says `embedder()` raises `NotImplementedError`; `docs/history/`; README says DirectML is the default while `onnx_engine.py:59` says CPU | Current-state docstrings; history to the wiki |
| Identity strings | `lookup.USER_AGENT = "Vibedentify/1.0 (+…/Vibe_Identify)"` (`lookup.py:25`) | Build from `__version__` and this repo's URL |
| Diagnostics | `_rss_mb` (`routes/analysis.py:376-413`) | Remove once the decode-once fix lands |
| Fixtures | `oracle/index.json` with `/mnt/c/Users/<you>/…` paths | Hashes and bare filenames |
| Requirements | `pywebview` listed in both `requirements-dev.txt` and `desktop/requirements-desktop.txt`; `pytest` in `requirements.txt` | One runtime file, one dev file, one lock |

## Order of work

Each line is sized to be one Claude Code task with its own PR; the phases are ordered so nothing later has to be redone.

**Phase 0 — same day, no design decisions**

- [ ] Delete MAEST and the /compare route + Compare panel (`analysis.py`, `routes/analysis.py`, `.env.example`, `models/discogs-maest-*.json`)
- [ ] Add `tests/test_no_essentia.py` (import scan over `src/ desktop/ tools/ training/`)
- [ ] Port `training/embed_extract.py` to `decode` + `onnx_engine` — decided: the training feature stays
- [x] Fix the NUL byte in `app.js`; add a control-character check to pre-commit
- [ ] Add `timeout=120` to both `subprocess.run` calls in `decode.py`
- [ ] Unify the provider policy: `tempo.py` imports `PROVIDER_ORDER` from `onnx_engine`
- [ ] Add the double-checked build lock to `onnx_engine.get_engine()`
- [ ] `/forget` deletes from all seven tables
- [ ] Name the columns in `db.cache_put`
- [ ] Generate a lockfile; pin ruff once; make CI install from the lock

**Phase 1 — user-visible failures**

- [ ] Move `settings.ini`, `taxonomy.json`, `vibe_snapshots/` to `%APPDATA%\Vibe Identify\`; seed from the installer-written file once
- [ ] Make `GENRE_TOKEN` mandatory; print the `?k=` URL in `__main__`
- [ ] JSON-only bodies + `Origin` check on every mutating route; `secure_filename` on uploads; `/save_training` and `/compare` only accept paths already in `tracks.filepath`
- [ ] Discogs credentials to the `Authorization` header
- [ ] Cancellable `/batch` (cancel event, lazy submit, `cancel_futures=True`) with a Cancel button and `AbortController` on the client
- [ ] Replace the Werkzeug dev server with waitress in `genre_app.pyw` and `__main__.py`

**Phase 2 — engine and data paths (re-run the oracle gate after)**

- [ ] Decode once per track (`pan=mono|c0=0.5*c0+0.5*c1`, float32, resample twice from one buffer); remove `_rss_mb`
- [ ] Denormalized columns (`style`, `bpm`, `key`, `scale`, `camelot`, `duration`) via migration 6; rewrite `/library`, `/similar`, `/training/candidates` against them
- [ ] Indexes on `vibe_tracks(hash)`, `track_tags(hash)`, `training_labels(hash, genre)`, `segment_overrides(hash)`
- [ ] Cache `/map` and `insight.audit()` on `(COUNT(*), MAX(created))`
- [ ] Thread-local connections; retire `_db_lock` for reads

**Phase 3 — structure (one PR each, in this order)**

- [ ] `Settings` object passed to `create_app`; delete the module-reload hack in `tests/conftest.py`
- [ ] Repository layer under `vibenative/repo/`; routes contain no SQL
- [ ] One `dominant_style()`; one `@bp.errorhandler`; `trainsets` stops importing from `routes`
- [ ] `fake_engine.py` behind the engine contract; FAKE branches removed from routes and `analysis.py`
- [ ] Dedupe: sanitizer and training root via `trainsets`; one mel filterbank; drop the 19 lazy numpy imports
- [ ] `taxonomy/` package replacing the six genre sources
- [ ] Frontend to ES modules; delete the eslint globals list
- [ ] `/api/v1` prefix; DELETE verbs; one product name; version read from `pyproject.toml`

**Phase 4 — the license work (can start in parallel with Phase 1; gates any sale)**

- [ ] Ask MTG/UPF about a commercial license for the models — the answer decides the rest of this phase
- [ ] Define the accuracy benchmark before touching any model: agreement with the 121-track oracle plus ~200 hand-labelled tracks from the library (genre, BPM, key); every engine change in this phase reports against it
- [ ] Rewrite `key.py` from the literature on librosa/scipy; re-baseline against the benchmark at ≥ 90%
- [ ] Re-derive both mel frontends from librosa definitions; counsel confirms the README provenance note can go
- [ ] If no license: pick a permissive embedder and tempo estimator, retrain the genre head on the 400-label taxonomy, retire `tools/convert_models.py` and `requirements-convert.txt`
- [ ] `pip-licenses --fail-on` in CI; exclude `data/` from the PyInstaller spec until the crawled data is cleared

**Phase 5 — proving it**

- [ ] `windows-latest` CI job with `onnxruntime-directml` + ffmpeg and an engine smoke test
- [ ] Code signing
- [ ] Delete the remaining legacy table (Section 8) and `docs/history/`

**Post-release**

- [ ] `platform.py` collecting the Windows-isms (Maintainability #10)
- [ ] macOS port: CoreML execution provider, `open -R` for `/reveal`, pywebview on WebKit; `secure_filename` is already in place from Phase 1
- [ ] A second-model ensemble only if a licensed second model exists; until then `/compare` stays gone

**Decisions (2026-09-23)**

- Custom-head training is critical: it stays and is ported in Phase 0; the relabel path stays with it.
- `/compare` is removed with MAEST. Accuracy is pursued through the Phase 4 benchmark and the model choice, not a per-track A/B panel.
- macOS is post-release; `platform.py` moves there.

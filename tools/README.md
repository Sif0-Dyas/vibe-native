# tools/

Developer scripts. None of these ship, none run in CI, and every one of them is
safe to re-run — they skip work that is already done rather than redoing it.
Each script's own docstring is the real documentation (`python tools/X.py --help`);
this page exists so you can tell at a glance which one you want.

Run them with the project venv: `.venv\Scripts\python tools/<script>.py`.

## Releasing

Run in this order; `build_exe.py` does all three for you.

| script | what it does |
|---|---|
| `build_exe.py` | PyInstaller onedir build → `dist/Vibe Identify/`, then prepare, then smoke-test. **The one to run.** |
| `prepare_dist.py` | Copies the deliberately-unbundled resources beside the exe: ONNX models, and an LGPL ffmpeg/ffprobe (vendored on first run) so redistribution is not bound by a GPL build. |
| `smoke_dist.py` | Launches the built exe and checks it serves: version, bundled ffmpeg, ONNX providers, UI page, static assets. Runs with `PATH` cut back to the Windows system dirs, because a dev box with ffmpeg installed will otherwise pass a bundle that is broken everywhere else. |
| `build_installer.py` | Inno Setup installer from the packaged folder. |

A build that has not passed `smoke_dist.py` should not be sent to anyone: the
failure modes of PyInstaller (a missing hiddenimport, an uncollected DLL) all
produce a complete-looking `dist/` folder that dies on the target machine.

## Models

| script | what it does |
|---|---|
| `convert_models.py` | Builds `models/*.onnx` from MTG's TensorFlow originals. Needs the conversion venv (Python ≤3.12 + `requirements-convert.txt`); see `CONVERSION_NOTES.md`. |

## The key detector

Fitting and scoring `vibenative.tonality`; the method and results are in
[`../docs/KEY_SPEC.md`](../docs/KEY_SPEC.md), the data in
[`../docs/DATASETS.md`](../docs/DATASETS.md).

| script | what it does |
|---|---|
| `eval_key.py` | Scores the detector against a labelled dataset (`--dataset giantsteps\|beatport\|both\|library\|oracle`) in MIREX categories. `--sweep` adds the front-end experiment grid. |
| `train_key_templates.py` | Fits the shipped model (the templates in `src/vibenative/data/key_profiles.json`) and cross-validates it. `--dataset library` trains on keys corrected in the app. |
| `fit_key_profiles.py` | The simpler baseline: per-mode median profiles, Faraldo 2017 §3.1. Kept as the fallback the app uses when no trained model is present. |
| `try_key_mlp.py` | A recorded dead end — a nonlinear scorer, which loses to the linear templates. Kept as the evidence behind the "what did not work" table in KEY_SPEC. |

## Reference data

| script | what it does |
|---|---|
| `crawl_genres.py` | Builds the electronic-genre reference from Wikidata, MusicBrainz, DBpedia and Wikipedia. By far the largest tool here, and the one that fights the network — expect it to need attention first. |
| `build_enao.py` | Builds the Every Noise at Once genre coordinate map from a locally saved page. |

## Migration and reference

| script | what it does |
|---|---|
| `db_cutover.py` | Copies a WSL Vibe_Identify library DB to `GENRE_DB`. Once per machine that still has the old app; reads the original only. |
| `make_oracle.py` | Dumps golden-reference analysis from the old WSL app. Run in WSL. Produces `oracle/`, which the regression tests compare against. |

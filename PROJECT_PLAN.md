# Vibe Native — Project Plan

Native-Windows rebuild of Vibe_Identify's analysis engine. The existing
WSL app stays untouched: it remains the daily driver AND the validation
oracle this project is measured against.

## Why this is feasible

Essentia is the ONLY component of Vibe_Identify that cannot run natively on
Windows (no Windows Python wheels; officially unsupported). Everything else —
Flask, SQLite, vibes/tags/map logic, the whole frontend, the training
pipeline — is platform-independent and ports nearly as-is. This project
replaces one module's internals (`analysis.py`) and repackages.

The models themselves are portable: the EffNet embedder and Discogs-400 head
are frozen TensorFlow graphs that Essentia merely *hosts*. Converted to ONNX,
they run under ONNX Runtime, which has first-class Windows support — and its
DirectML backend runs on the RTX 5070. GPU acceleration, a hard dead-end in
WSL (TF 2.5 vs CUDA vs Blackwell), falls out of the native build for free.

## The one real risk, and how it's neutralized

Essentia computes the mel-spectrogram frontend with exact parameters; the
models are only valid on inputs that match EXACTLY. "Close" silently degrades
accuracy. Mitigation: the working WSL build is a perfect oracle. We dump
reference embeddings/BPM/key for a diverse test set (tools/make_oracle.py,
runs today) and the native frontend is DONE when its embeddings hit cosine
similarity > 0.999 against the reference. CI enforces this forever. The
riskiest part of the project becomes a measurable, bisectable target.

## Architecture

    decode        ffmpeg (native Windows binary, subprocess) -> float32 PCM
    genre         mel frontend (ours, oracle-validated)
                    -> effnet.onnx (embedder, 1280-dim frames)
                    -> genre400.onnx (classifier head)
                  via ONNX Runtime; DirectML EP when available, CPU fallback
    tempo         tempocnn.onnx (Essentia model zoo) — NOT librosa beat
                  tracking (a quality step down from RhythmExtractor2013)
    key           chroma-profile correlation vs 24 key templates (~50 lines
                  over librosa chroma), oracle-validated
    everything    routes.py / db.py / insight.py / static/ / templates/ /
    else          training/ ported from Vibe_Identify with minimal edits
                  (config paths, remove /mnt/c assumptions)

Same DB schema -> the native build can inherit the existing genre_v2.db
(cache, vibes, tags) unchanged.

Frontend/architecture decision (made): keep Flask + browser. Maximum reuse,
the UI is already good. A desktop shell (Tauri) can wrap it later if wanted.

## Mel frontend parameters (starting point — VERIFY against Essentia source)

Discogs-EffNet expects (per MTG model cards + Essentia defaults for
TensorflowPredictEffnetDiscogs):
  - 16000 Hz mono input
  - frameSize 512, hopSize 256 (spectrogram)
  - 96 mel bands, HTK-style mel scale, magnitude -> log10 compression
    with Essentia's specific shift/scale ("log10(1+10000*x)" style — CONFIRM
    in essentia source: src/algorithms/spectral/melbands + the
    TensorflowInputMusiCNN/FSDSINet-style frontends; EffNet uses
    TensorflowInputMusiCNN-compatible mel config — VERIFY)
  - patches of 128 frames, patchHopSize 62 (coarse) — the app's fine mode
    used patchHopSize 32-equivalent (~0.51s); keep both as parameters
  - batch dimension 64 (bs64 graph) — pad/trim final batch
Do not trust this list. Phase 2's first task is reading the Essentia source
and the model card, then encoding the truth into frontend_mel.py. The oracle
decides.

## Phases

### Phase 0 — Oracle (run in the EXISTING WSL environment; ~1 evening)
Run `tools/make_oracle.py` on WSL against a diverse test set (aim: 50 tracks
spanning your genres, some edge cases: quiet intros, vinyl rips, mono files,
different formats/bitrates). It imports vibedentify directly and writes, per
track, into oracle/:
  <hash>.npz  — embeddings (coarse), emb_mean, preds
  index.json  — hash -> {file, bpm, bpm_confidence, key, scale, camelot,
                duration, top styles}
Copy the oracle/ folder into THIS repo (it's gitignored by size; keep a
backup). Also copy the three model files from ~/essentia_models into models/.

### Phase 1 — ONNX conversion + inference skeleton
Convert effnet + genre head (+ TempoCNN, downloaded from the Essentia model
zoo) to ONNX with tf2onnx. Verify each converted model in isolation: feed it
oracle mel-inputs/embeddings and compare outputs. Deliverable:
`native/vibenative/onnx_engine.py` passing tests/test_onnx_models.py.

### Phase 2 — Mel frontend (THE go/no-go phase)
Implement `frontend_mel.py` from the verified parameters. Iterate against
tests/test_oracle_match.py until cosine(native_emb, oracle_emb) > 0.999 for
every track and frame counts match. If this converges, the project succeeds;
everything downstream only consumes embeddings and scores.

### Phase 3 — Tempo + key
`tempo.py` (TempoCNN via ONNX) and `key.py` (chroma correlation). Acceptance:
key exact-match >= 90% vs oracle (log disagreements — some are genuinely
ambiguous); BPM within 2% OR a half/double multiple for >= 95% of tracks
(the app's UI already handles the octave ambiguity).

### Phase 4 — Port the app
Copy routes/db/insight/static/templates/training from Vibe_Identify. Replace
analysis.py internals with the native engine BEHIND THE SAME function
signatures (get_engine, analyze, refine_segments, custom_predict contract,
build_payload shape). Windows-ize config (paths, GENRE_DB default under
%USERPROFILE%). FAKE_ANALYZER mode must keep working — it's how tests run.
Batch route: accept BOTH Windows paths natively and (for muscle memory)
translate /mnt/c/... back to C:\...

### Phase 5 — Package
requirements.txt (onnxruntime-directml, flask, mutagen, numpy, librosa or a
minimal stft/chroma impl, soundfile) + a launcher .bat; optionally PyInstaller
single-exe. GPU: try DirectML EP, fall back to CPU, log which one engaged.

## Claude Code prompts (one per session)

### Session A (phases 0-1)
> Read PROJECT_PLAN.md fully, then tools/make_oracle.py and the stubs in
> native/vibenative/. I've already run the oracle on WSL; oracle/ and models/
> are populated. Do Phase 1: write tools/convert_models.py (tf2onnx) for the
> three .pb models into models/*.onnx, then implement onnx_engine.py to its
> docstring contract, then make tests/test_onnx_models.py pass (it feeds
> oracle embeddings through genre400.onnx and compares preds to the oracle's
> stored preds). Don't start the mel frontend. Ask me anything ambiguous
> before writing code.

### Session B (phase 2)
> Phase 2 per PROJECT_PLAN.md. First read the Essentia source for the EffNet
> input frontend (melbands config, log compression, patch layout) and write
> what you find as comments into frontend_mel.py before implementing. Then
> iterate until tests/test_oracle_match.py passes at cosine > 0.999 on every
> oracle track. If you plateau below that, STOP and report the per-track
> similarity distribution + your hypothesis — do not lower the threshold.

### Session C (phase 3)
> Phase 3 per PROJECT_PLAN.md: tempo.py (TempoCNN ONNX) and key.py (chroma
> correlation vs 24 templates — use the Krumhansl/temperley profiles Essentia
> uses; check its KeyExtractor defaults). Acceptance thresholds are in the
> plan; report the disagreement lists rather than hiding them.

### Session D (phase 4)
> Phase 4: port the app from the Vibe_Identify repo (I'll place a checkout at
> ../Vibe_Identify). Keep analysis.py's public contract identical; swap
> internals to the native engine. All existing tests from that repo must pass
> here in FAKE mode, plus the oracle tests in real mode.

### Session E (phase 5)
> Phase 5: packaging per the plan. Launcher .bat first, PyInstaller only if
> the .bat flow works end to end.

## Risks & honest notes
- Mel mismatch is the project. If Phase 2 stalls despite matching documented
  params, diff at each stage (raw frames -> spectrogram -> mel -> log) against
  values extracted from Essentia on WSL; add a tools/dump_stages.py there.
- tf2onnx on TF1-style frozen graphs occasionally needs --inputs/--outputs
  flags with the exact tensor names (they're in Vibe_Identify's analysis.py:
  embedder output "PartitionedCall:1", classifier input
  "serving_default_model_Placeholder", output "PartitionedCall:0").
- onnxruntime-directml vs onnxruntime: install ONE (they conflict).
- librosa pulls numba; if packaging pain, replace with hand-rolled
  stft/mel/chroma (we control exact params anyway — may end up MORE correct).
- BPM parity is "good enough + octave-aware", not bit-exact. Accept it.

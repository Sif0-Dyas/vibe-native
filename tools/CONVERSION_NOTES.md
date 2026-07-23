# Conversion Notes — Phase 1 (TensorFlow models → ONNX)

## Interpreter constraint (why Python ≤ 3.12)

- **Conversion requires Python ≤ 3.12.** TensorFlow ships **no wheels for Python
  3.14** (`pip install tensorflow` → *"No matching distribution found"*), and
  `tf2onnx` needs TensorFlow to load SavedModels / frozen graphs. This machine had
  only 3.14 installed, so we installed **3.12.10** (`winget install
  Python.Python.3.12`) and pin it at the repo root via **`.python-version` (`3.12`)**
  so future sessions don't rediscover this.
- **Runtime is version-flexible.** `onnxruntime-directml`, `numpy`, and `pytest`
  all have 3.14 wheels — only the *conversion* half is version-locked. The produced
  `models/*.onnx` are portable and run under any supported Python.
- Dependencies are split so the heavy TF wheel never ships:
  - `requirements-convert.txt` — `tensorflow`, `tf2onnx` (conversion only, ~500 MB)
  - `requirements.txt` — `onnxruntime-directml`, `numpy`, `pytest` (runtime + tests)

## Toolchain versions (this machine)

| Tool | Version |
| --- | --- |
| Python | 3.12.10 (venv at `.venv/`) |
| tensorflow (convert-only) | 2.21.0 |
| tf2onnx | 1.17.0 |
| onnx | 1.22.0 |
| onnxruntime-directml | 1.24.4 |
| numpy | 2.5.1 |
| Execution providers present | `DmlExecutionProvider`, `CPUExecutionProvider` |

## Zoo-ONNX pre-check (Task 2)

Checked <https://essentia.upf.edu/models/> on 2026-07-22 — a download beats a
conversion (addendum §2):

| Model | Ready-made `.onnx` in the zoo? | Decision |
| --- | --- | --- |
| EffNet embedder | **Yes** — `discogs-effnet-bsdynamic-1.onnx` (dynamic batch; `melspectrogram[B,128,96]` → `embeddings[B,1280]` + `activations[B,400]`) | **Downloaded** → `models/effnet.onnx`; no conversion |
| genre_discogs400 head (EffNet variant) | **No** — only MAEST variants ship `.onnx` | **Converted** `genre_discogs400-discogs-effnet-1.pb` |
| TempoCNN `deeptemp-k16` | **No** — only `.pb` / `.json` / `.tfjs` | **Converted** `deeptemp-k16-3.pb` |

The SavedModel→ONNX path for the embedder (plan Task 3a) is retained as a fallback
in `convert_models.py` (`_convert_effnet_from_savedmodel`), used only if the
ready-made download is unavailable.

## Source models + conversion results (Task 3)

`opset = 17`; tf2onnx `--graphdef` (frozen-graph) path for the two `.pb` heads.

| Output | Source | Input node → Output node | Result |
| --- | --- | --- | --- |
| `effnet.onnx` | zoo `discogs-effnet-bsdynamic-1.onnx` | `melspectrogram[B,128,96]` → `embeddings[B,1280]` | downloaded, 18.0 MB |
| `genre400.onnx` | `genre_discogs400-discogs-effnet-1.pb` | `serving_default_model_Placeholder:0[B,1280]` → `PartitionedCall:0[B,400]` (Sigmoid) | converted, 2.05 MB |
| `tempocnn.onnx` | `deeptemp-k16-3.pb` | `input:0[B,40,T,1]` → `output:0[B,256]` (Softmax) | converted, 1.28 MB |

**Genre-head fidelity vs the oracle (Phase-1 acceptance):** feeding every oracle
track's stored 1280-d embeddings through `genre400.onnx` and comparing the
mean-over-frames top-5 to `index.json` — **all 121 tracks match names exactly;
worst |Δscore| = 5.96e-08** (tolerance 1e-3). The baked-in Sigmoid converted
cleanly — no double activation, wrong output node, or transposed input.

## Execution provider that engaged on this machine

`get_engine()` logs the provider it selected; on this machine (RTX 5070) it
engaged **`DmlExecutionProvider`** (DirectML). onnxruntime-directml 1.24.4 reports
available providers: `DmlExecutionProvider`, `CPUExecutionProvider`.

## Handoff to Phase 2 (mel frontend)

1. **Authoritative embedder input spec.** `models/effnet.onnx` is the zoo's
   `discogs-effnet-bsdynamic-1`. Read its tracked metadata
   `models/discogs-effnet-bsdynamic-1.json` **before** the Essentia source — it
   pins `serving_default_melspectrogram [n, 128, 96]`, `sample_rate 16000`, and
   `embeddings = PartitionedCall:1 [n, 1280]`. The JSON fixes the 128×96 patch
   shape + sample rate; the exact mel filterbank / log compression still comes
   from the Essentia source but must reproduce that patch shape. (See the header
   of `native/vibenative/frontend_mel.py`.)
2. **Iteration strategy.** The oracle has 121 tracks. Iterate the frontend against
   a **~40-track subset** for a fast inner loop, and run the **full 121** only as
   the final acceptance gate. Never lower the cosine > 0.999 threshold.

---

# Phase 2 — Mel frontend (the go/no-go phase): **PASSED**

Native mel frontend + EffNet embedder reproduce the WSL oracle's embeddings to
**cosine > 0.999 on all 121 tracks** (worst 0.99932, mean 0.99982; per-track
mean-embedding *and* mean per-frame both > 0.999; frame counts match 121/121).
Full-121 gate ~77 s; ~40-track subset ~27 s. ffmpeg is a **runtime prerequisite**
(`winget install ffmpeg`) — the Phase-4/5 app needs it wherever it runs.

## Verified mel parameters (from the Essentia source, not the plan's hypothesis)

Discogs-EffNet input = Essentia `TensorflowInputMusiCNN`, driven by
`TensorflowPredictEffnetDiscogs`:

- 16 kHz mono; FrameCutter `frameSize 512, hopSize 256`, `startFromZero=false`
  (first frame centered at 0). — `tensorflowpredicteffnetdiscogs.{cpp,h}`
- Windowing `hann`, `normalized=false`.
- Power spectrum `|rfft|**2`; MelBands 96 bands, 0–8000 Hz, `warpingFormula
  slaneyMel`, `weighting linear`, `normalize unit_tri` (= divide each triangle by
  `(f_hi−f_lo)/2`, the source comment: "similar to how normalization is
  implemented in Librosa" = Slaney area norm), `type=power` (squares the spectrum).
  — `melbands.cpp`, `triangularbands.cpp`
- Log compression **`log10(1 + 10000·mel_power)`**. — essentia-labs, *TensorFlow
  models in Essentia* (2019-10-19): `UnaryOperator(shift=1, scale=10000)` then
  `UnaryOperator(type='log10')`.
- Patches 128×96, `patchHopSize 62` (coarse; smaller = the app's fine mode),
  `lastPatchMode discard`.

Confirmed **exact**: my mel on Essentia's *own* decoded audio matches Essentia's
mel band-for-band (linear-power ratio 1.0000, log-mel cosine 1.00000), and those
embeddings match the oracle at cosine 1.00000. The embedder JSON spec
(`[n,128,96]`, 16 kHz) agrees — no contradiction.

## Decode approach (the entire residual lived here)

Reproduces Essentia MonoLoader = AudioLoader → MonoMixer → Resample:

1. ffmpeg → native-rate float32 PCM (all channels).
2. downmix **`(L+R)/2`** (amplitude average = Essentia MonoMixer 'mix'). ffmpeg's
   own `-ac 1` uses energy-preserving `(L+R)/√2` — 1/√2 too loud, which shifts the
   whole log-mel (surfaced as a c≈0.5 mel-scale symptom). Decode all channels and
   average ourselves.
3. resample to 16 kHz by **linear interpolation** — Essentia `resampleQuality=4` =
   libsamplerate `SRC_LINEAR` — with a group-delay phase `RESAMPLE_PHASE = −1.24`
   input samples, calibrated against Essentia's actual 16 kHz output. numpy-only:
   no librosa/samplerate runtime dependency.

## How it was diagnosed (stage-by-stage diff vs Essentia — the plan's Risks note)

Plateaued at cos ≈ 0.927. Ruled out in order: hann symmetric-vs-periodic (no
effect), magnitude-vs-power (power confirmed), resampler *quality* (soxr didn't
help). Then dumped Essentia's real mel + decoded audio from the WSL Essentia venv
(`2.1-beta6-dev`) and diffed each stage:

- my mel == Essentia mel on identical audio → **frontend exact** (ratio 1.0000).
- `embed(Essentia audio)` == oracle → **whole pipeline exact** (cos 1.00000).
- ffmpeg `(L+R)/2` == Essentia native mono → **decode/downmix exact** (cos 1.000000).
- the sole residual was the resampler; linear + the −1.24 phase closes it to
  > 0.999 on all 121 (validated across 44.1 and 48 kHz sources).

---

# Phase 3 — Tempo + Key

## Tempo (TempoCNN): **PASSED** — 96.7%

Reproduces the oracle BPM within 2% OR a half/double multiple for **117/121 =
96.7%** of tracks (acceptance ≥ 95%). Frontend = Essentia TensorflowInputTempoCNN
= librosa **magnitude** mel (sr 11025, n_fft 1024, hop 512, power=1, 40 bands,
fmin 20, fmax 5000, slaney norm, **no log**; non-centered frames) — verified vs
Essentia's own mel to maxdiff 0.018. Class *i* → BPM = 30 + *i*·256/255
(`deeptemp-k16-3.json`). Aggregation: **average the per-patch 256-bin softmaxes**
(256-frame patches, hop 128) then argmax — beats Essentia's default "majority"
vote against the oracle (96.7% vs 95.0%). Verified my ONNX pipeline on Essentia's
own mel reproduces Essentia TempoCNN (125→125, etc.). The 4 misses: 2 are genuine
TempoCNN-vs-RhythmExtractor2013 disagreements (mine == Essentia TempoCNN, both ≠
oracle), 2 are octave picks where mine diverges from Essentia on ambiguous tracks.

## Key (native HPCP + KeyExtractor port): **PASSED** — 100%

Reproduces Essentia KeyExtractor's key **exactly (key + scale) on 121/121 tracks**
(acceptance ≥ 90%). `native/vibenative/key.py` is a stage-for-stage numpy port of
KeyExtractor, validated against per-stage WSL Essentia dumps (the Phase-2 playbook).

**Pipeline** (KeyExtractor's exact config, `keyextractor.cpp`): 44100 Hz mono →
FrameCutter 4096/4096 startFromZero → Windowing(hann) → Spectrum → SpectralPeaks
(magThresh 1e-4, 25–3500 Hz, 60 peaks) → SpectralWhitening → HPCP(size 12, ref 440,
harmonics 4, cosine, windowSize 1.0, bandPreset false, nonLinear false, normalized
none) → mean over frames → Key(profileType **bgate**, usePolyphony false,
numHarmonics 4, slope 0.6).

**What the earlier scaffold missed.** The Key *selection* was never the problem —
feeding Essentia's own mean HPCP through bgate-Pearson (12 circular shifts,
`index=(i-shift)%12`, minor wins ties, keyNames flats with **bin 0 = A**) already
reproduces the oracle **121/121**. With a size-12 HPCP and `usePolyphony=false`,
`Key` uses the **raw** bgate profiles (the resize() harmonic-interpolation loop is
empty when n=1). The entire burden was reproducing Essentia's **HPCP**, which
requires the full SpectralPeaks + **SpectralWhitening** + HPCP chain (the previous
"~55% on the mean chroma" was a *no-whitening* chroma; whitening is essential).

**Ported faithfully from source** (essentia 2.1-beta6):
- *SpectralPeaks* = `standard/peakdetection.cpp`: strict local maxima with parabolic
  interpolation, `pos = bin·(SR/2)/(N−1)`. A vectorized finder (`_spectral_peaks_fast`)
  is verified bit-identical to the literal port; the one subtlety is that Essentia's
  loop starts *at* `i0=ceil(minFreq/scale)` and climbs, so bin `i0` is reported only
  by the low-edge boundary check, never as an interior peak (else a phantom ~37 Hz
  peak appears).
- *SpectralWhitening* = `spectral/spectralwhitening.cpp`: 100 Hz-resolution power
  envelope BPF, per-peak `db` difference to it. Two gotchas that cost the accuracy:
  1. **Window normalization matters.** Essentia `Windowing(normalized=true)` scales
     the window by `2/Σ|w|` (≈1/1024). This is *not* globally scale-invariant because
     SpectralPeaks' `magnitudeThreshold` and the whitening passthrough are **absolute**
     — without it, silent frames sprout 60 phantom peaks.
  2. **essentia `lin2db`/`db2lin` use `10·log10` / `10^(x/10)`**, not 20/20. Getting
     this wrong under-applies the whitening's `−20·freq/4000` tilt by exactly a factor
     of `10^(freq/8000)` (a clean frequency-dependent error), which flipped ~10% of
     tracks between relative/parallel major-minor. Fixing it took 90.1% → 100%.
  3. The installed build whitens peaks up to `_maxFreq` itself (not `_maxFreq−incr`
     as the source's passthrough reads) — verified from per-peak dumps.
- *HPCP* = `spectral/hpcp.cpp`: harmonic-contribution table (`initHarmonicContribution
  Table`, 5 harmonics → fundamental strength 3.0 + fifth + major-third), cosine window
  `cos(π·distance)`, accumulate `weight·mag²·strength²`, **no** normalization.

Result: native mean HPCP vs Essentia's mean HPCP is cosine ~1.00000 across the
validation tracks; native key == oracle key 121/121. Acceptance test:
`tests/test_key.py` (subset by default, `VIBE_FULL_ORACLE=1` for all 121).

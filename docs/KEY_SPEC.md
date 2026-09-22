# Key detection — clean-room specification

This document is the *only* input to `src/vibenative/tonality.py`. It is written
from published papers and textbook DSP; nothing in it was taken from Essentia's
source, and the implementation must be written from this spec without opening
the AGPL Essentia port it replaced (the former `src/vibenative/key.py`, in git
history) or any Essentia code.

## Sources (all public)

- Krumhansl, C. & Kessler, E. (1982). *Tracing the dynamic changes in perceived
  tonal organization in a spatial representation of musical keys.* Psychological
  Review 89(4). — the original major/minor key profiles, numbers published in the
  paper and reproduced in every MIR textbook.
- Temperley, D. (1999). *What's key for key? The Krumhansl-Schmuckler key-finding
  algorithm reconsidered.* Music Perception 17(1). — revised profiles.
- Gómez, E. (2006). *Tonal description of music audio signals.* PhD thesis, UPF. —
  the pitch-class-profile-from-spectrum method (HPCP) in general terms: spectral
  peaks mapped to 12 pitch classes with tuning correction, aggregated over the
  track, correlated against key templates.
- Faraldo, Á., Gómez, E., Jordà, S., Herrera, P. (2016). *Key estimation in
  electronic dance music.* ECIR. — EDM-specific findings: minor-mode bias, the
  value of corpus-derived profiles.
- Faraldo, Á., Jordà, S., Herrera, P. (2017). *A multi-profile method for key
  estimation in EDM.* AES Semantic Audio. CC-BY-4.0, copy in
  `docs/papers/faraldo2017_multiprofile_edm.pdf`. — pipeline description: 4096-sample
  frames, 200 Hz high-pass, spectral whitening, global PCP, normalise to 1, gate
  bins under 0.2, detuning correction, correlate with profiles, **profiles built as
  the median PCP of correctly-labelled tracks per mode**.
- Müller, M. (2015). *Fundamentals of Music Processing.* Springer. — log-frequency
  / chroma feature construction, log compression, tuning estimation.

## Pipeline

Input: mono float32 audio at 44 100 Hz (from `decode.decode_mono`, which is an
ffmpeg wrapper and not part of this spec).

1. **Framing.** Hann-windowed frames of N = 8192 samples, hop 4096 (50 % overlap).
   Frames whose RMS is below 1e-4 are skipped (silence).
2. **Spectrum.** Magnitude of the real FFT, max-normalised per frame, restricted to
   15 Hz – 5 kHz. (The first draft high-passed at 200 Hz following Faraldo 2017;
   on this corpus that discards the bassline, which in house/techno carries most
   of the tonal information, and cost ~15 points. Above 5 kHz is noise and
   partials we do not model.)
3. **Peak selection.** Per frame, keep only local maxima (a bin larger than both
   neighbours) that are ≥ 1 % of the frame max, and of those only the 150 strongest
   (Gómez 2006: pitch content lives in a few strong peaks). This is the single
   most important step: a noisy spectrum has a local maximum every few bins, and
   without the cap those swamp the real partials and flatten the profile.
   Magnitudes are used linearly — log compression (γ = 10…100) and squaring were
   both tried and lost, because compression lifts the residual noise peaks.
4. **Tuning estimation.** From peaks above 500 Hz only (below that a bin is wider
   than the tuning resolution): fractional MIDI pitch `p = 69 + 12·log2(f / 440)`,
   fraction `p − round(p)` histogrammed in 5-cent bins (odd count, so one bin is
   centred on "in tune"), weighted by peak magnitude. The mode is the global
   offset `δ` — but only if it is ≥ 2× the mean bin; a flat histogram means noise
   and the track is treated as A440. On this corpus the gate fires on ~20 % of
   tracks and changes no decisions; it exists for genuinely detuned material.
5. **Pitch-class profile (PCP).** Each retained bin's pitch `p_k − δ` goes to pitch
   class `round(p_k − δ) mod 12` (0 = C … 11 = B) with weight `cos²(π·(p_k − round
   p_k))`, so energy between two semitones is split. Sub-harmonic crediting
   (a peak at f also credits f/2, f/3 …, as HPCP does) was evaluated at depths
   2–8 and did not help once peaks were capped; it is implemented but off.
6. **Aggregation.** Each frame's PCP is max-normalised (so loud sections do not
   dominate), then averaged over non-silent frames, then max-normalised again.
   Bins under 0.2 are zeroed (PCP gate, Faraldo 2017) — on this corpus it never
   fires with the profiles below, but it is cheap and matches the paper.
7. **Template matching.** For each of the 24 keys (12 tonics × {major, minor})
   rotate the mode's profile so index 0 is the tonic and compute the Pearson
   correlation with the global PCP. The best score wins. `strength` is the winning
   correlation. Ties broken toward minor (EDM prior, Faraldo 2016).
8. **Output.** `(key_name, "major"|"minor", strength)` with names spelled
   `C C# D Eb E F F# G Ab A Bb B` (the spelling the app's Camelot table and the
   existing database use).

## Profiles

Two published sets are built in verbatim from the papers:

- `kk` — Krumhansl & Kessler 1982.
- `temperley` — Temperley 1999.

A third set, `edm`, is derived by this project from labelled audio using the recipe
in Faraldo 2017 §3.1: for each labelled track compute the global PCP (steps 1–6),
rotate it so the labelled tonic is index 0, and take the per-mode **median** across
tracks. `tools/fit_key_profiles.py` does this with leave-one-out cross-validation so
the reported accuracy is honest; the fitted vectors are stored in
`src/vibenative/data/key_profiles.json` with the provenance recorded in the file.
The labels used for fitting are the app's own key annotations (whatever the
library says the key is); the vectors are statistics of our own audio, not copies
of anyone's constants.

## Evaluation

`tools/eval_key.py --loo` runs the detector over `oracle/index.json` and reports
agreement with the reference key/scale labels, broken down by exact match,
relative (major↔relative minor), parallel (same tonic, other mode), fifth
(tonic a fifth away), and other — the MIREX key-detection categories — for each
profile set. Result on the 121-track corpus (2026-09-21):

| profiles              | exact        | fifth | relative | parallel | other | MIREX |
|-----------------------|--------------|-------|----------|----------|-------|-------|
| Krumhansl–Kessler     | 60 (49.6 %)  | 20    | 4        | 23       | 14    | 0.626 |
| Temperley             | 53 (43.8 %)  | 14    | 20       | 6        | 28    | 0.555 |
| `edm` (leave-one-out) | 96 (79.3 %)  | 7     | 3        | 9        | 6     | 0.845 |

This measures *agreement with the previous detector* (Essentia's `bgate`
KeyExtractor), not ground truth: Faraldo 2017 Table 1 reports `bgate` itself at
64 % exact (MIREX 0.73) on the human-labelled GiantSteps set and 64–66 % on two
others, with Mixed In Key at 66–72 %. Two imperfect detectors agreeing on ~80 %
is consistent with both being in that range; it says nothing about which one is
right on the other 20 %. Genuine accuracy needs
human labels — the public GiantSteps key dataset (604 Beatport excerpts, expert
annotated) is the obvious next step, both to score and to refit the profiles
on ~5× more data.

## Non-goals

- Bit-matching the previous implementation. Different frame size, window,
  compression and chroma mapping are deliberate.
- Key changes within a track. One global key per track, as before.

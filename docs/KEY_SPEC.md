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
   the block's band (step 7); the whole-band block high-passes at 200 Hz as in
   Faraldo 2017, the bass block starts at 25 Hz. Above 5 kHz is noise and
   partials we do not model.
3. **Peak selection.** Per frame, keep only local maxima (a bin larger than both
   neighbours) that are ≥ 1 % of the frame max, and of those only the N strongest
   (N = 100 for the whole band, 16 for a single band; see step 7)
   (Gómez 2006: pitch content lives in a few strong peaks). This is the single
   most important step: a noisy spectrum has a local maximum every few bins, and
   without the cap those swamp the real partials and flatten the profile.
   Magnitudes are used linearly — log compression (γ = 10…100) and squaring were
   both tried and lost, because compression lifts the residual noise peaks.
   Each retained peak also credits the pitch classes of f/2 … f/5 with weight
   1/h (a partial may be a harmonic of a lower note; HPCP does the same).
4. **Tuning estimation.** From peaks above 500 Hz only (below that a bin is wider
   than the tuning resolution): fractional MIDI pitch `p = 69 + 12·log2(f / 440)`,
   fraction `p − round(p)` histogrammed in 5-cent bins (odd count, so one bin is
   centred on "in tune"), weighted by peak magnitude. The mode is the global
   offset `δ` — but only if it is ≥ 2× the mean bin; a flat histogram means noise
   and the track is treated as A440. The gate fires on ~20 % of tracks and
   rarely changes a decision; it exists for genuinely detuned material. Only the
   whole-band block is tuning-corrected (a single band is too narrow to
   estimate it).
5. **Pitch-class profile (PCP).** Each retained bin's pitch `p_k − δ` goes to pitch
   class `round(p_k − δ) mod 12` (0 = C … 11 = B) with weight `cos²(π·(p_k − round
   p_k))`, so energy between two semitones is split.
6. **Aggregation.** Each frame's PCP is max-normalised (so loud sections do not
   dominate), then averaged over non-silent frames, then max-normalised again.
   Bins under 0.2 are zeroed (PCP gate, Faraldo 2017).
7. **Multi-band features.** Steps 2–6 are run four times with different bands
   and peak caps, giving four 12-bin PCPs that are concatenated (48 values):
   the whole band (200 Hz – 5 kHz, 100 peaks, tuning-corrected), the bass
   (25–400 Hz, 16 peaks), the low-mids (200 Hz – 1 kHz, 16 peaks) and the
   top (1–5 kHz, 16 peaks). The bass PCP is the strongest *tonic* cue in EDM
   (Mauch & Dixon 2010 use a separate bass chroma for the same reason); the
   whole-band PCP carries the *mode*. Each block is standardised (zero mean,
   unit norm) so a dot product with a template is a Pearson correlation.
8. **Scoring.** For each of the 24 keys, every block is rotated so the candidate
   tonic sits at index 0 and the concatenation is dotted with the mode's trained
   48-weight template, plus a per-mode bias. The highest score wins; `strength`
   is the winner's softmax probability over the 24 keys (0–1). Silence (no
   peaks anywhere) reports strength 0.
9. **Output.** `(key_name, "major"|"minor", strength)` with names spelled
   `C C# D Eb E F F# G Ab A Bb B` (the spelling the app's Camelot table and the
   existing database use).

## Templates

The weights are **trained**, not hand-written: `tools/train_key_templates.py`
fits the two 48-vectors and two biases as a transposition-equivariant 24-way
softmax (multinomial logistic regression over the rotated, standardised
features, L2 = 1e-3) on the GiantSteps key dataset — 604 two-minute Beatport
excerpts with expert-corrected labels (Knees, Faraldo et al., ISMIR 2015). It
is exactly the classical template-matching model (Krumhansl 1990, Gómez 2006),
with the templates chosen to *separate* keys rather than to describe the
average one. The result lives in `src/vibenative/data/key_profiles.json` under
`"model"` with its blocks, cross-validation and provenance.

Three 12-bin profile sets are kept as a baseline/fallback for the single
whole-band PCP: Krumhansl–Kessler 1982 and Temperley 1999 verbatim from the
papers, and `edm`, the per-mode median of tonic-rotated GiantSteps PCPs
(Faraldo 2017 §3.1 recipe; `tools/fit_key_profiles.py`).

## Evaluation

`tools/eval_key.py --dataset giantsteps|oracle` scores the shipped model and
the profile sets in the MIREX categories: exact, fifth (tonic a fifth away, same
mode), relative (major ↔ relative minor), parallel (same tonic, other mode),
other. Results, 2026-09-22:

**GiantSteps, 604 human-labelled tracks** (the model's number is 5-fold
cross-validated; the paper's numbers are from Faraldo 2017 Tables 1–2 on the
same set):

| detector                                   | exact      | fifth | relative | parallel | other | MIREX     |
|--------------------------------------------|------------|-------|----------|----------|-------|-----------|
| Krumhansl–Kessler, whole-band PCP          | 34.9 %     | 87    | 40       | 102      | 164   | 0.475     |
| `edm` median profiles, whole-band (LOO)    | 52.6 %     | 67    | 52       | 41       | 126   | 0.621     |
| trained, whole-band only (5-fold)          | 61.3 %     | 64    | 31       | 26       | 113   | 0.690     |
| **trained, 4 bands (5-fold) — shipped**    | **66.6 %** | 54    | 20       | 31       | 97    | **0.730** |
| Essentia `bgate` (the old detector, paper) | 64.1 %     |       |          |          |       | 0.725     |
| KeyFinder (paper)                          | 60.4 %     |       |          |          |       | 0.699     |
| Mixed In Key 7 (paper)                     | 67.2 %     |       |          |          |       | 0.742     |

**Oracle corpus, 121 tracks from this library** — labels are the *old
detector's output*, so this is agreement, not accuracy; the model never saw
these tracks:

| detector                                  | agrees with old detector |
|-------------------------------------------|--------------------------|
| shipped model                             | 88/121 (72.7 %)          |
| `edm` median profiles (fit on GiantSteps) | 93/121 (76.9 %)          |

The two detectors disagree on ~27 % of the library. Which is right there is
unknowable without human labels; on the set that has them, the model is 2.5
points ahead of the old detector. What the sweeps established along the way,
all on GiantSteps: front-end settings (cutoff, peak cap, compression,
sub-harmonics, frame size, tuning) move a single-PCP detector only within
51–55 %; the gains came from training the templates (+6) and adding the band
PCPs (+5).

## Non-goals

- Bit-matching the previous implementation. Different frame size, window,
  compression and chroma mapping are deliberate.
- Key changes within a track. One global key per track, as before.

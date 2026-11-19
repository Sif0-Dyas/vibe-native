# Embedder bake-off — first real run, 2026-11-19

`tools/bakeoff.py` against the blind labels collected on `/label` so far. The
question it answers: with a keystone-level logistic-regression head trained on
labels we own, which permissively licensed embedder comes closest to the MTG
EffNet embedding the app ships today? See `REMEDIATION_PLAN.md` Phase 4 and
`PROVENANCE.md`, "Candidate embedders (not shipped)", for why.

**Read this first.** Only part of the library was reachable (the F: drive was not
mounted), the training set is 79% House, and Techno has 8 training tracks. The
numbers below are the first real measurement, not the benchmark the retrain will
be judged on. Nothing here is a smoke test; everything here is small.

## Setup

- Labels: `export_labels.py` over a backup-API copy of the library database
  (6,162 tracks), 2,026 rows: override 29, weight 9, id3-genre 1,802, blind 35,
  blind-contested 151.
- Split: a track with a `blind` or `blind-contested` label is a **test** track and
  nothing else; its id3 row is dropped from training (163 rows dropped). Every
  other track with an override, weight or id3-genre label **trains**, one label
  per track in that priority. The code asserts the two sets share no hash.
  Labels are mapped to keystones with `tagcheck.keystone_for`, the resolver
  `/label` and the Analyzer use; labels with no keystone are left out (3 blind:
  Moombahton, Midtempo Bass ×2; 527 training, mostly tags naming no genre the
  taxonomy knows).
- Training keystones with fewer than 5 tracks are dropped (Disco 2, Hip Hop 2,
  Electro 2, Ambient, Experimental, Punk, Hard Dance, Downtempo 1 each). A test
  track whose keystone was never trained stays in the test set and counts as a
  miss.
- Head: `StandardScaler` + `LogisticRegression(class_weight="balanced",
  max_iter=5000)`, fitted once per line on the training embeddings, predicting
  every test track. Macro-F1 is over the keystones present in the labels or the
  predictions of that table.
- Audio: 48 kHz mono decode, centred 60 s cut, resampled per candidate,
  embeddings mean-pooled over time. The EffNet reference is the stored
  whole-track embedding, so it sees more audio than any candidate.
- Two references. **effnet**: the stored EffNet embedding under the same head on
  the same training tracks. **model-read**: the shipped model's own top style
  (`weights.base_read`, no override or adjustment) mapped to its keystone — no
  training at all.
- Hardware: CPU only (torch 2.14 CPU build in `.venv-bakeoff`; the RTX 5070 was
  not used). Reference-line numbers do not depend on this.

### What was reachable

| | labelled tracks | readable | left out |
|---|---|---|---|
| train | 1,148 (with a keystone) | 546 → 535 after trimming thin keystones | 516 on the unmounted F: drive, 62 with no path, 24 missing |
| test | 183 (with a keystone) | 183 | 0 |

Training sources: id3-genre 538, weight 7, override 1. Training keystones:
House 421, Trance 57, Drum n Bass 26, Dubstep 12, **Techno 8**, Breakbeat 6,
Trap 5.

Test keystones: House 145, Trance 22, Drum n Bass 4, Breakbeat 4, Techno 4,
Experimental 2, Trap 1, Dubstep 1.

## CLAP windowing fix (done before the run)

The old chunker, `range(0, len - n//2, n)`, silently dropped up to 5 s at the
tail of any cut that was not a multiple of 10 s (14 s → one 10 s window, 65 s →
60 s). `CLAP.windows` now lays 10 s windows back to back and, when audio is left
over, adds a last window aligned to the end (overlapping the previous one), so
nothing is dropped and no window exceeds 10 s — a longer window would hit the
processor's `rand_trunc` random crop and make the embedding non-deterministic.
Probed before the fix: per-window embeddings are L2-normalised, batched and
single-window outputs agree, and 60 s cuts were already covered exactly, so the
fix changes only tracks shorter than the cut. The CLAP cache was discarded and
all 718 tracks re-embedded.

## Results

### Table 1 — blind (random sample), 33 tracks

Labels: House 22, Drum n Bass 4, Trance 3, Breakbeat 2, Trap 1, Dubstep 1.

| | effnet | model-read | yamnet | openl3 | panns | clap |
|---|---|---|---|---|---|---|
| accuracy | **0.939** | 0.848 | 0.667 | 0.636 | 0.758 | 0.636 |
| macro-F1 | **0.774** | 0.402 | 0.288 | 0.264 | 0.371 | 0.233 |
| House P / R (n=22) | 0.96 / 1.00 | 1.00 / 0.91 | 0.76 / 0.86 | 0.75 / 0.82 | 0.83 / 0.91 | 0.78 / 0.82 |

Confusion counts, label → predicted:

| | effnet | model-read | yamnet | openl3 | panns | clap |
|---|---|---|---|---|---|---|
| House → Techno | 0 | 2 | 0 | 0 | 0 | 1 |
| Techno → House | 0 | 0 | 0 | 0 | 0 | 0 |
| Trance → House | 0 | 0 | 2 | 1 | 1 | 1 |
| House → Trance | 0 | 0 | 3 | 3 | 2 | 2 |

No other keystone reaches 10 test labels, so there are no further per-keystone
rows. With 33 tracks, one track is 3 points of accuracy; the gap between effnet
and the best candidate (panns, 6 tracks) is real at this size, the ordering among
the four candidates (2–4 tracks apart) is not.

### Table 2 — blind-contested, 150 tracks

Labels: House 123, Trance 19, Techno 4, Experimental 2, Breakbeat 2.

**model-read is selected against this model.** These are exactly the tracks
where the shipped model's read and the file tag named different keystones, so its
column is the share of those disagreements the labeller settled in the model's
favour (8 of 150), not an accuracy. The other lines are not selected against,
but the sample is still not the library: it is 82% House tracks the model
called Techno.

| | effnet | model-read* | yamnet | openl3 | panns | clap |
|---|---|---|---|---|---|---|
| accuracy | **0.860** | 0.053 | 0.833 | 0.807 | 0.780 | 0.773 |
| macro-F1 | **0.307** | 0.022 | 0.222 | 0.205 | 0.187 | 0.195 |
| House P / R (n=123) | 0.90 / 0.95 | 0.27 / 0.06 | 0.90 / 0.91 | 0.91 / 0.89 | 0.86 / 0.92 | 0.90 / 0.86 |
| Trance P / R (n=19) | 0.69 / 0.58 | 0.00 / 0.00 | 0.62 / 0.68 | 0.50 / 0.58 | 0.27 / 0.21 | 0.45 / 0.53 |

Confusion counts, label → predicted:

| | effnet | model-read* | yamnet | openl3 | panns | clap |
|---|---|---|---|---|---|---|
| House → Techno | 2 | 107 | 3 | 2 | 1 | 1 |
| Techno → House | 3 | 2 | 3 | 3 | 2 | 2 |
| Trance → House | 7 | 16 | 6 | 5 | 14 | 6 |
| House → Trance | 4 | 9 | 8 | 11 | 9 | 12 |

Macro-F1 is low for every line here because the table has five label keystones
and three of them (Techno 4, Experimental 2, Breakbeat 2) are rarely or never
predicted: Experimental was dropped from training, Techno trained on 8 tracks.

### Wall time

| | yamnet | openl3 | panns | clap |
|---|---|---|---|---|
| embed, s per 60 s track (CPU) | 0.06 | 5.31 | 0.96 | 0.50 |
| tracks timed | 24 | 24 | 24 | 718 |
| model load, s | 5.5 | 1.5 | 0.6 | 4.1 |

Decode: 1.00 s per track over 718 tracks, shared. Head fit + predict: ≤ 0.3 s
per line. Whole extraction: 1,230 s. YAMNet, PANNs and OpenL3 were timed only on
the 24 tracks not already in the cache from the smoke run; CLAP on everything,
after its cache was discarded.

## Reading

1. **EffNet with a retrained head leads both tables**, and on the contested
   table it fixes almost all of what the shipped head gets wrong there
   (House → Techno 107 → 2). Most of the contested-set error is in the shipped
   400-style head, not the embedding. That does not make the embedding usable:
   its licence is the problem being solved (PROVENANCE §1–2).
2. **No candidate matches EffNet.** On the random sample the best candidate
   (PANNs) is 18 points behind on accuracy and half the macro-F1; on the
   contested sample YAMNet is closest (3 points behind). Every candidate loses
   Trance to House more than EffNet does.
3. **The head cannot learn Techno from 8 tracks**, so the House/Techno boundary —
   the one the contested set was built around — is untested for every trained
   line. Techno → House is 2–3 for all of them; that is 4 test tracks.
4. **YAMNet is the cheapest by far** (0.06 s per track on CPU, 1024-d) and the
   best candidate on the contested table; PANNs the best on the random table.
   OpenL3 costs 90× YAMNet for no gain here.

## Before this is a benchmark

- Mount F: and re-run: 516 training tracks (half the training set) and their
  keystone mix are missing. The cache makes the re-run cost only the new tracks.
- Label more Techno, Trance, Drum n Bass and Breakbeat on `/label` with
  "Contested first" **off**: the random sample is 33 tracks and six keystones,
  and only House clears 10 labels in it.
- The 60 s cut handicaps every candidate against the whole-track EffNet
  reference; run `--seconds 0` once the set is settled.
- Consider a GPU torch build in `.venv-bakeoff` if OpenL3 stays in the running.

Run: `UV_PROJECT_ENVIRONMENT=.venv-bakeoff uv run --group bakeoff python
tools/bakeoff.py labels.csv --db <db copy> --out bakeoff.json`. Harness commit:
see `git log -- tools/bakeoff.py`.

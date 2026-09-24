# Provenance and licensing inventory

Every component in this app that came from somewhere else: what it is, where it
came from, what licence governs it, whether it reaches a customer, and what the
exposure is if the app is sold. Written to be read by a lawyer or a reviewer who
has never seen the code.

**Not legal advice.** This is an engineer's inventory of the facts, assembled by
reading the code and the upstream licences. The judgement calls are flagged as
judgement calls.

Audited 2026-09-22 against commit `54a27f1`. Re-run the checks in
[How to re-verify](#how-to-re-verify) after any dependency or model change.

---

## Summary

| # | Component | Origin | Licence | Reaches customer | Blocks a sale? |
|---|---|---|---|---|---|
| 1 | `models/effnet.onnx`, `genre400.onnx` | MTG / UPF | **CC BY-NC-ND 4.0** | yes, beside the exe | **YES** |
| 2 | `models/tempocnn.onnx` | MTG / UPF | **CC BY-NC-ND 4.0** | yes, beside the exe | **YES** |
| 3 | `frontend_mel.py` | textbook DSP; parameters read from Essentia | disputed — see below | yes | probably not |
| 4 | `decode.py`, `tempo.py` frontends | behaviour matched to Essentia | disputed — see below | yes | probably not |
| 5 | `data/key_profiles.json` | trained on GiantSteps + Beatport EDM Key | training-data question | yes | unclear |
| 6 | `data/enao.json` | everynoise.com scrape (6,291 Spotify genres) | **none stated** | no — excluded from the build; its fields stripped from #7 | no, while it stays out |
| 7 | `data/genres_electronic.json` | Wikidata/MusicBrainz + DBpedia/Wikipedia | CC0 + **CC BY-SA** | **yes, inside the exe** | attribution + share-alike |
| 8 | `mutagen` | Python package | **GPL-2.0** | **yes**, inside the exe | **YES** — being removed |
| 9 | ffmpeg / ffprobe | BtbN LGPL static build | **LGPL** | yes, beside the exe | no, handled |
| 10 | onnxruntime, numpy, flask, pywebview | PyPI | MIT / BSD | yes | no |
| 11 | `oracle/` + `paths.wsl_to_windows` | the predecessor WSL app | n/a — dev asset | no (tests only) | no |
| 12 | `tonality.py` + tests + app code | this project | MIT | yes | no |

**The single blocker is #1 and #2.** Everything else is either already fine,
cheaply fixable, or hangs off those models (see the dependency chain below).

---

## The dependency chain

This is the thing to understand before spending any effort:

```
  CC BY-NC-ND models (effnet, genre400, tempocnn)      <-- the root
        ^                    ^
        |                    |
  frontend_mel.py      tempo.py frontend      exist ONLY to feed those models
        ^                    ^
        |                    |
            decode.py                         matches the frontends' input
                ^
                |
            oracle/                           exists ONLY to prove the above
                ^                              reproduce the predecessor app
                |
        WSL references                        exist ONLY because the oracle
                                               was produced under WSL
```

Replacing the models removes the whole stack. Removing the WSL references at the
bottom changes nothing about the licence position — it only removes the
explanation of how the code came to be.

---

## 1–2. The MTG models — the actual blocker

`models/effnet.onnx` (Discogs-EffNet embedder), `models/genre400.onnx`
(Discogs-400 style head) and `models/tempocnn.onnx` (DeepTemp k16) are
converted from MTG's published TensorFlow models, released under
**CC BY-NC-ND 4.0**:

- **NC — non-commercial.** Selling a product that ships them is outside the
  licence. This is not a grey area.
- **ND — no derivatives.** `tools/convert_models.py` converts `.pb` to `.onnx`.
  A format conversion is arguably a derivative work.

Model cards and citations: `models/*.json` carry MTG's own `citation` and `link`
fields. Papers: Alonso-Jiménez et al., ISMIR 2022 (genre); Schreiber & Müller,
SMC 2019 (tempo).

**Options:** (a) commercial licence from MTG/UPF — they invite enquiries for
exactly this; (b) replace with permissively-licensed models (PANNs, YAMNet,
OpenL3, CLAP are MIT/Apache) plus a head trained on data you can use; (c) a paid
tagging API. Only (a) and (b) keep the feature in-process.

## 3–4. The Essentia-derived frontends

`README.md` currently states that `frontend_mel.py` is a stage-for-stage port of
Essentia (AGPL-3.0) and therefore AGPL. **Having read it, I think that claim is
overcautious, and it is worth a lawyer's five minutes to settle**, because it is
the difference between "one AGPL file in a commercial product" and "no AGPL at
all".

What the file actually contains (130 lines):

- a Hann window — `0.5 - 0.5*cos(2πi/(N-1))`, the textbook definition;
- a Slaney mel filterbank built from **Slaney's published 1998 constants**
  (`f_sp = 200/3`, `min_log_hz = 1000`, `logstep = log(6.4)/27`) — the same
  values librosa uses under ISC;
- triangular filters with area normalisation, `numpy.fft.rfft`, and
  `log10(1 + 10000·x)`.

The Essentia citations in its header are for **parameter values** — facts about
what input the model expects — not for code structure. Facts are not
copyrightable; expression is.

Contrast the file this project already removed: the old `key.py` had functions
named "Port of `HPCP::compute`", "Port of `PeakDetection::compute`", mirroring
Essentia's call graph function by function. *That* was a derivative work, and it
was replaced clean-room by `tonality.py` (see `KEY_SPEC.md`). `frontend_mel.py`
is a different kind of artefact.

`decode.py` and `tempo.py`'s frontend are the same story: they match observable
*behaviour* (mono downmix, resample rate, mel parameters) of a pipeline, using
ffmpeg and numpy.

Note this is moot if the models are replaced — these files exist only to feed
them.

## 5. The trained key model

`src/vibenative/data/key_profiles.json` holds weights fitted on the GiantSteps
key dataset and the Beatport EDM Key dataset (**CC BY-SA 4.0** annotations); see
`DATASETS.md`. The audio in both is Beatport's, distributed for research.

The common position is that model weights are not a derivative work of their
training data, but this is unsettled, and CC BY-SA's share-alike clause is
exactly the kind of term that invites the argument. The clean answer is to
retrain on data the product owns — which the app now collects, via the key
corrections feature (`key_labels` table, `--dataset library`).

## 6. `data/enao.json` — undocumented, and no longer ships

6,291 Spotify genre names with x/y/colour coordinates, scraped from
everynoise.com (`tools/build_enao.py`). **No licence is stated anywhere** — not on
the source site, not in the README's licensing section, not in the file.

As audited, it shipped: it is `.gitignore`d, but the PyInstaller spec collected the
whole package data directory, so the file was **inside the exe**
(`_internal/vibenative/data/enao.json`, verified in a real build). Not being in git
is irrelevant to redistribution. Its data also reached the exe a second way: the
genre crawler copied an `everynoise` block (colour, x/y, size) into 300 of the 610
records of `genres_electronic.json` (#7).

**Resolved (updated 2026-09-23; the rest of this document is as audited at
`54a27f1`):**

- The spec excludes it (`collect_data_files(..., excludes=["data/enao.json"])`,
  commit `87dd357`), and `tools/smoke_dist.py` fails a build that contains any
  `enao.json`.
- The crawler no longer copies ENAO data, and `tools/strip_enao_fields.py` removed
  it from the existing `genres_electronic.json` (commit `960c078`); `smoke_dist.py`
  fails a build whose copy has any `everynoise` field. The Wikidata P9881 ID
  (`everynoise_id`, CC0) is kept.
- Nothing in the running app reads the snapshot — `vibenative.enao` has no callers,
  and the map is laid out from track-embedding similarity — so excluding it costs
  no functionality.

## 7. `data/genres_electronic.json` — attribution obligations, and it ships

Aggregated from Wikidata and MusicBrainz (CC0, no obligations) and from DBpedia /
Wikipedia prose (**CC BY-SA**). The file carries its own `licences` block and
per-record `sources`, which is the right instinct. But it is bundled in the exe
the same way, so the attribution has to travel with the *product*, where a user
can see it — not only inside a JSON file. Share-alike may also reach any adapted
text.

## 8. `mutagen` — GPL, and it ships

`mutagen` (GPL-2.0) was in `requirements.txt` and imported by
`analysis.read_title` / `read_tags` to read track tags.

Unlike ffmpeg — which is invoked as a separate program via argv, the textbook
"mere aggregation" position the README argues correctly — mutagen is *imported*
into the process. For a proprietary product that is the classic copyleft
problem, and it is the one dependency here that is genuinely incompatible with
selling a closed-source binary.

It **is** redistributed. `Vibe Identify.spec` lists `mutagen` in `hiddenimports`,
and the build embeds it in the PYZ archive inside the exe
(`build/Vibe Identify/PYZ-00.toc` lists `mutagen\__init__.py` and friends).

> An earlier revision of this document claimed mutagen was *not* shipped and that
> tag reading was therefore silently broken in the packaged app. That was wrong,
> and wrong in the direction that matters: it came from looking for loose files
> under `_internal/` and finding none. PyInstaller puts pure-Python packages in
> the embedded PYZ archive, not on disk, so the absence of files proved nothing.
> Tag reading worked; the licence exposure was real and current.

**Resolved** by `src/vibenative/metadata.py`, which reads tags with ffprobe —
already shipped for decoding, LGPL, separate process. Verified field-for-field
against mutagen on all 121 oracle tracks: **identical on 120**. The single
difference is a FLAC carrying two GENRE fields, where ffprobe returns both
("Dubstep;Electronic") and mutagen returned only the first.

## 9–10. Dependencies that are fine

- **ffmpeg/ffprobe** — LGPL static build from BtbN, vendored by
  `tools/prepare_dist.py`, invoked as a separate program, `ffmpeg-NOTICE.txt`
  shipped alongside. This is handled properly and is the model for how the other
  items should look.
- **onnxruntime-directml** (MIT), **numpy** (BSD), **flask** (BSD),
  **pywebview** (BSD). No obligations beyond notice.

## 11. The WSL lineage — not a licence issue

Worth stating plainly for a reviewer, because the word appears throughout the
history: WSL is Microsoft's Linux runtime. Developing the predecessor under it
creates no obligation of any kind. What the WSL references point at is:

- `oracle/` — cached analysis output from the predecessor app, used by tests as
  a regression reference. Developer asset, never shipped, not in git.
- `paths.wsl_to_windows` and schema migration #2 — translate `/mnt/c/...` paths
  stored in a library database inherited from the predecessor. A legacy-import
  feature, dead code for a fresh install.
- `tools/db_cutover.py`, `tools/make_oracle.py` — developer scripts for the
  same migration.

None of this is encumbered. It should be tidied because it is confusing and
serves almost nobody, not because it is risky.

---

## What would make this clean

In the order that actually removes exposure:

1. **Resolve the models** (#1, #2). Licence them or replace them. Nothing else
   unblocks a sale, and it collapses #3 and #4 with it.
2. **Drop mutagen** (#8). Cheap, removes the only copyleft dependency, and fixes
   a real bug in the shipped product.
3. **Settle `enao.json`** (#6). **Done: it no longer ships**, and neither does the
   ENAO data that had been copied into `genres_electronic.json`. Only if a future
   feature wants ENAO's colours or coordinates does this reopen — then it needs
   permission or an owned replacement first.
4. **Surface the CC BY-SA attribution** (#7) somewhere a user of the product can
   read, not only inside a bundled JSON file.
5. **Retrain the key model on owned data** (#5), which the app now collects.
6. **Isolate or retire the legacy-import path** (#11). Cosmetic, cheap, makes
   the codebase legible.

## What NOT to do

**Do not remove the provenance comments.** If a file *is* a derivative work,
deleting the header that says so does not change that; it destroys the evidence
of good-faith attribution and makes the position look worse, not better. A
reviewer's first question is "where did this come from" — the answer should be
in the file. The goal is provenance that is *complete and legible*, not absent.

## How to re-verify

```bash
# what actually ships
find "dist/Vibe Identify" -name "*.json" -path "*data*"
find "dist/Vibe Identify" -iname "*mutagen*"        # expect: nothing

# dependency licences
for p in mutagen flask numpy onnxruntime-directml pywebview; do
  ls -d .venv/Lib/site-packages/${p}*dist-info/licenses/* ; done

# code that cites an upstream implementation
grep -rniE "essentia|ported|port of" --include="*.py" src/
```

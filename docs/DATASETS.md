# Evaluation datasets

None of this ships. `datasets/` is git-ignored; the tools fetch it on demand and
cache the derived pitch-class profiles in `datasets/cache/*.npz`. What *does*
ship is `src/vibenative/data/key_profiles.json` — the trained weights.

## GiantSteps key dataset — 604 tracks

Knees, Faraldo, Boyer, Vogl, Böck, Hörschläger, Le Goff, *"Two data sets for
tempo estimation and key detection in electronic dance music annotated from user
corrections"*, ISMIR 2015. Beatport preview excerpts with keys corrected by users
in the Beatport forums.

```
cd datasets && git clone --depth 1 https://github.com/GiantSteps/giantsteps-key-dataset
cd giantsteps-key-dataset && bash audio_dl.sh      # ~850 MB
```

Beatport's own preview URLs are dead; the script's JKU mirror
(`https://www.cp.jku.at/datasets/giantsteps/backup/`) still serves, and every
file is md5-verified against `md5/`. Annotations are in the repo, MIT-licensed;
the audio is Beatport's, distributed for research.

## Beatport EDM Key dataset — 1,486 excerpts, 1,275 usable

Faraldo, *"Tonality estimation in electronic dance music: a computational and
musically informed examination"*, PhD thesis, UPF 2017.
[zenodo.org/records/1101082](https://zenodo.org/records/1101082),
**CC BY-SA 4.0**. Annotated by two experts, with a 0–2 confidence level and
comments per track.

```
cd datasets/beatport-edm-key
curl -LO "https://zenodo.org/records/1101082/files/audio.zip?download=1"     # 2.1 GB
curl -LO "https://zenodo.org/records/1101082/files/keys.zip?download=1"
curl -LO "https://zenodo.org/records/1101082/files/Beatport-EDM-Key-Dataset.xlsx?download=1"
unzip audio.zip && unzip keys.zip
```

`eval_key.load_index("beatport")` keeps only single-key labels: it drops the 73
tracks marked `X` (no key) and the 136 with two keys or a modal label
(`F minor phrygian`, `C# minor | E major`). `meta.xlsx` supplies the confidence
level, which `train_key_templates.py --min-confidence` can filter on.

**Licensing note for a commercial build.** CC BY-SA covers the *annotations*;
the audio is again Beatport's, for research. Training weights on a share-alike
dataset is a question a lawyer should answer before the model ships in a paid
product — the usual argument is that model weights are not a derivative work of
the training data, but it is not settled, and the safe path is either to retrain
on data you own (the app's own corrections) or to get written permission. The
same caveat applies to GiantSteps.

## The two sets do not agree

Trained on one, tested on the other, held out:

| trained on            | → GiantSteps | → Beatport |
|-----------------------|--------------|------------|
| GiantSteps (604)      | 67.2 %       | 55.3 %     |
| Beatport (1,275)      | 62.7 %       | 60.7 %     |
| both (1,879)          | 66.6 %       | 60.6 %     |

Adding Beatport to GiantSteps training *lowers* the GiantSteps score (67.2 →
65.4): they label differently — Beatport is expert-annotated with 30 % major
tracks, GiantSteps is forum-corrected with 15 % — so a model fitted to one is
mis-calibrated for the other. Union training gives up ~0.5 points on each and
gets a model that holds up on both, which is what the app ships.

The practical lesson: **key accuracy is distribution-specific**. The best
training set for this app is not a public one, it is the user's own corrections.

## Oracle corpus — 121 tracks

`oracle/index.json`, this library's own tracks, labelled by the *old* Essentia
KeyExtractor port. Useful as a regression check against the previous engine,
useless as ground truth — a disagreement there does not mean an error.

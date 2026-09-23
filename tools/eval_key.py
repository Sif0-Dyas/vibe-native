"""Accuracy of the clean-room key detector (vibenative.tonality) against labelled
datasets, per profile set, in MIREX categories.

    python tools/eval_key.py                          # oracle corpus, built-in profiles
    python tools/eval_key.py --loo                    # + leave-one-out corpus-fitted profiles
    python tools/eval_key.py --dataset giantsteps     # human-labelled GiantSteps (604 tracks)
    python tools/eval_key.py --dataset oracle --fit-on giantsteps   # cross-dataset
    python tools/eval_key.py --dataset giantsteps --sweep --loo     # front-end experiments

The "shipped model" line is the multi-band model in data/key_profiles.json (what
the app runs); the per-variant lines score single 12-bin profile sets on the
whole-band PCP.

Datasets:
  oracle      oracle/index.json — labels are Essentia's KeyExtractor output (agreement, not truth)
  giantsteps  datasets/giantsteps-key-dataset — expert-corrected Beatport labels (Knees et al.
              ISMIR 2015). Clone https://github.com/GiantSteps/giantsteps-key-dataset into
              datasets/ and fetch audio/ with its audio_dl.sh (the JKU mirror still serves).
  beatport    datasets/beatport-edm-key — Beatport EDM Key Dataset (Faraldo 2017, CC BY-SA 4.0,
              zenodo.org/records/1101082): 1486 excerpts, of which 1287 carry a single key.
              Unzip audio.zip and keys.zip into datasets/beatport-edm-key/.
  both        giantsteps + beatport, ids prefixed with the dataset name.
  library     this app's own corrected keys (the key_labels table). The best
              training set there is, because it is the distribution the app serves;
              grows every time someone fixes a key in the UI.

Global PCPs are cached in datasets/cache/<dataset>.npz (keyed by track id + variant)
so re-running after a profile tweak takes seconds, not minutes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vibenative import tonality  # noqa: E402
from vibenative.decode import decode_mono  # noqa: E402
from vibenative.legacy import wsl_to_windows  # noqa: E402

ORACLE = ROOT / "oracle"
DATASETS = ROOT / "datasets"
CACHE_DIR = DATASETS / "cache"
# GiantSteps spells with flats; the app (and the oracle) use C# and F#.
SPELLING = {"Db": "C#", "Gb": "F#", "D#": "Eb", "G#": "Ab", "A#": "Bb"}
# name -> pcp_from_magnitudes() kwargs. Every variant shares one decode + FFT per track.
# "default" is what the app ships; add entries here to sweep a setting.
VARIANTS: dict[str, dict] = {"default": {}}
if tonality.MODEL:  # the shipped model's blocks, so it can be scored from the cache
    for _i, _blk in enumerate(tonality.MODEL["blocks"]):
        VARIANTS[f"model block {_i}"] = dict(_blk)

# Opt-in front-end experiments (--sweep): whole-band settings, and single bands
# whose PCPs tools/train_key_templates.py can concatenate into a multi-band model.
SWEEP: dict[str, dict] = {}
_BASE = dict(f_lo=200, top_peaks=100, subharmonics=4, tuning=True)
SWEEP["base"] = dict(_BASE)
for _flo in (15, 60, 200):
    for _top in (40, 100, 150, 0):
        for _sub in (0, 4):
            SWEEP[f"flo={_flo} top={_top} sub={_sub}"] = dict(f_lo=_flo, top_peaks=_top, subharmonics=_sub, tuning=True)
for _lo, _hi in ((25, 400), (400, 1500), (1500, 5000), (200, 1000), (1000, 5000)):
    for _tp in (16, 50):
        SWEEP[f"band {_lo}-{_hi} peaks={_tp}"] = dict(f_lo=_lo, f_hi=_hi, top_peaks=_tp, subharmonics=4, tuning=False)
# octave-spaced bands: a chroma per octave, which is what a listener hears
OCTAVES = [(25, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, 1600), (1600, 3200), (3200, 5000)]
for _lo, _hi in OCTAVES:
    SWEEP[f"oct {_lo}"] = dict(f_lo=_lo, f_hi=_hi, top_peaks=16, subharmonics=4, tuning=False)
    SWEEP[f"oct {_lo} p4"] = dict(f_lo=_lo, f_hi=_hi, top_peaks=4, subharmonics=4, tuning=False)
for _sec in ("loud", "quiet"):
    for _frac in (0.15, 0.3):
        SWEEP[f"{_sec}{_frac:g} whole"] = dict(_BASE, section=_sec, section_frac=_frac)
        SWEEP[f"{_sec}{_frac:g} bass"] = dict(f_lo=25, f_hi=400, top_peaks=16, subharmonics=4,
                                              tuning=False, section=_sec, section_frac=_frac)


def variant_settings(name: str) -> dict:
    """pcp_from_magnitudes kwargs for a variant from either table."""
    if name in VARIANTS:
        return VARIANTS[name]
    if name in SWEEP:
        return SWEEP[name]
    sys.exit(f"unknown variant {name!r}")


def _beatport_confidence(root: Path) -> dict[str, int]:
    """{track id: annotator confidence 0-2} from the dataset's spreadsheet, if
    openpyxl is installed; an empty dict (all None) otherwise."""
    book = root / "meta.xlsx"
    if not book.exists():
        return {}
    try:
        import openpyxl
    except ImportError:
        return {}
    rows = list(openpyxl.load_workbook(book, read_only=True).active.values)
    hdr = [str(c or "").lower() for c in rows[0]]
    i_id, i_conf = hdr.index("id"), hdr.index("confidence")
    return {str(r[i_id]): int(r[i_conf]) for r in rows[1:] if r[i_id] is not None and r[i_conf] is not None}


def load_index(dataset: str = "oracle") -> dict:
    """{id: {"file": path, "key": name, "scale": mode, ...}} for a dataset."""
    if dataset == "both":
        return {f"{d}:{k}": v for d in ("giantsteps", "beatport") for k, v in load_index(d).items()}
    if dataset == "oracle":
        idx = json.loads((ORACLE / "index.json").read_text(encoding="utf-8"))
        return {h: {**m, "file": wsl_to_windows(m["file"])} for h, m in idx.items()}
    if dataset == "giantsteps":
        root = DATASETS / "giantsteps-key-dataset"
        if not (root / "annotations" / "key").is_dir():
            sys.exit(f"{root} missing - see the docstring for how to fetch it")
        out = {}
        for f in sorted((root / "annotations" / "key").glob("*.key")):
            key, scale = f.read_text(encoding="utf-8").split()
            out[f.stem] = {"file": str(root / "audio" / f"{f.stem}.mp3"), "key": SPELLING.get(key, key), "scale": scale}
        return out
    if dataset == "library":
        sys.path.insert(0, str(ROOT / "src"))
        from vibenative.db import key_labels_all

        out = {}
        for h, filepath, key, scale in key_labels_all():
            if Path(filepath).exists():
                out[h] = {"file": filepath, "key": key, "scale": scale}
        if not out:
            sys.exit("no corrected keys yet - correct some in the app first")
        return out
    if dataset == "beatport":
        root = DATASETS / "beatport-edm-key"
        if not (root / "keys").is_dir():
            sys.exit(f"{root} missing - see the docstring for how to fetch it")
        conf = _beatport_confidence(root)
        out = {}
        for f in sorted((root / "keys").glob("*.txt")):
            label = f.read_text(encoding="utf-8", errors="replace").strip()
            parts = label.split()
            if len(parts) != 2 or parts[1] not in ("major", "minor"):
                continue  # "X" (no key), "F minor phrygian", "C# minor | E major": not a single key
            audio = root / "audio" / f"{f.stem}.mp3"
            out[f.stem] = {"file": str(audio), "key": SPELLING.get(parts[0], parts[0]), "scale": parts[1],
                           "confidence": conf.get(f.stem.split()[0])}
        return out
    sys.exit(f"unknown dataset {dataset!r}")


def load_pcps(index: dict, dataset: str = "oracle", verbose: bool = True) -> dict[tuple[str, str], np.ndarray]:
    """{(id, variant): pcp} for every track with audio on disk, via the cache."""
    if dataset == "both":  # reuse each dataset's own cache, keyed by prefixed id
        out = {}
        for d in ("giantsteps", "beatport"):
            sub = {k.split(":", 1)[1]: v for k, v in index.items() if k.startswith(f"{d}:")}
            for (h, n), v in load_pcps(sub, d, verbose).items():
                out[(f"{d}:{h}", n)] = v
        return out
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{dataset}.npz"
    cache: dict[str, np.ndarray] = {}
    if cache_file.exists():
        with np.load(cache_file) as z:
            cache = {k: z[k] for k in z.files}
    out = {}
    dirty = False
    for i, h in enumerate(sorted(index)):
        path = Path(index[h]["file"])
        if not path.exists():
            continue
        missing = [n for n in VARIANTS if f"{h}:{n}" not in cache]
        if missing:
            if verbose:
                print(f"[{i + 1}/{len(index)}] {path.name}".encode("ascii", "replace").decode(), flush=True)
            audio = decode_mono(path, tonality.SR)
            for frame in sorted({variant_settings(n).get("frame", tonality.FRAME) for n in missing}):
                mags, freqs = tonality.magnitudes(audio, tonality.SR, frame)
                for n in missing:
                    settings = {k: v for k, v in variant_settings(n).items() if k != "frame"}
                    if variant_settings(n).get("frame", tonality.FRAME) == frame:
                        cache[f"{h}:{n}"] = tonality.pcp_from_magnitudes(mags, freqs, **settings)
            dirty = True
            if i % 25 == 0:
                np.savez(cache_file, **cache)  # save as we go: decoding is the slow part
        for n in VARIANTS:
            out[(h, n)] = cache[f"{h}:{n}"]
    if dirty:
        np.savez(cache_file, **cache)
    return out


def category(pred: tuple[str, str], ref: tuple[str, str]) -> str:
    pk, pm = tonality.KEY_NAMES.index(pred[0]), pred[1]
    rk, rm = tonality.KEY_NAMES.index(ref[0]), ref[1]
    if (pk, pm) == (rk, rm):
        return "exact"
    if pm == rm and (pk - rk) % 12 in (5, 7):
        return "fifth"
    if pm != rm and pk == rk:
        return "parallel"
    if pm != rm and ((rm == "major" and (pk - rk) % 12 == 9) or (rm == "minor" and (pk - rk) % 12 == 3)):
        return "relative"
    return "other"


def gated(v: np.ndarray) -> np.ndarray:
    return np.where(v < tonality.GATE, 0.0, v)


def fit_profiles(pcps: dict, index: dict, hashes, variant: str) -> dict[str, np.ndarray]:
    """Faraldo 2017 §3.1: per-mode median of tonic-rotated global PCPs."""
    rows = {"major": [], "minor": []}
    for h in hashes:
        m = index[h]
        tonic = tonality.KEY_NAMES.index(m["key"])
        rows[m["scale"]].append(np.roll(pcps[(h, variant)], -tonic))
    return {mode: np.median(np.array(r), axis=0) for mode, r in rows.items() if r}


def evaluate(pcps: dict, index: dict, variant: str, profile: str | None = None, loo: bool = False) -> Counter:
    hashes = [h for h in sorted(index) if (h, variant) in pcps]
    cats: Counter = Counter()
    for h in hashes:
        if loo:
            others = [x for x in hashes if x != h]
            tonality.PROFILES["_loo"] = fit_profiles(pcps, index, others, variant)
            name = "_loo"
        else:
            name = profile
        k, s, _ = tonality.match(gated(pcps[(h, variant)]), name)
        cats[category((k, s), (index[h]["key"], index[h]["scale"]))] += 1
    tonality.PROFILES.pop("_loo", None)
    return cats


def evaluate_model(pcps: dict, index: dict) -> Counter:
    """The shipped multi-band model (tonality.MODEL) on the cached block PCPs."""
    names = [f"model block {i}" for i in range(len(tonality.MODEL["blocks"]))]
    cats: Counter = Counter()
    for h in sorted(index):
        if not all((h, n) in pcps for n in names):
            continue
        f = np.concatenate([gated(pcps[(h, n)]) for n in names])
        k, s, _ = tonality.match_model(f)
        cats[category((k, s), (index[h]["key"], index[h]["scale"]))] += 1
    return cats


def report(label: str, cats: Counter) -> None:
    n = sum(cats.values())
    mirex = (cats["exact"] + 0.5 * cats["fifth"] + 0.3 * cats["relative"] + 0.2 * cats["parallel"]) / n
    parts = "  ".join(f"{c}={cats[c]}" for c in ("exact", "fifth", "relative", "parallel", "other"))
    print(f"{label:<16} exact {cats['exact']:>3}/{n} ({100 * cats['exact'] / n:5.1f}%)  mirex {mirex:.3f}   {parts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="oracle", help="oracle | giantsteps | beatport | both")
    ap.add_argument("--loo", action="store_true", help="also score leave-one-out fitted profiles")
    ap.add_argument("--fit-on", metavar="DATASET", help="also score profiles fitted on this other dataset")
    ap.add_argument("--sweep", action="store_true", help="also compute and score the SWEEP front-end variants")
    args = ap.parse_args()
    if args.sweep:
        VARIANTS.update(SWEEP)

    index = load_index(args.dataset)
    pcps = load_pcps(index, args.dataset)
    n = len({h for h, _ in pcps})
    print(f"\n{args.dataset}: {n} tracks with audio\n")
    if tonality.MODEL:
        report("shipped model", evaluate_model(pcps, index))
        print()
    if args.fit_on:
        fit_index = load_index(args.fit_on)
        fit_pcps = load_pcps(fit_index, args.fit_on)
    for variant in VARIANTS:
        print(variant)
        for name in sorted(tonality.PROFILES):
            report(f"  {name}", evaluate(pcps, index, variant, profile=name))
        if args.loo:
            report("  fitted LOO", evaluate(pcps, index, variant, loo=True))
        if args.fit_on:
            hashes = [h for h in sorted(fit_index) if (h, variant) in fit_pcps]
            tonality.PROFILES["_x"] = fit_profiles(fit_pcps, fit_index, hashes, variant)
            report(f"  fit:{args.fit_on}", evaluate(pcps, index, variant, profile="_x"))
            tonality.PROFILES.pop("_x", None)
        print()


if __name__ == "__main__":
    main()

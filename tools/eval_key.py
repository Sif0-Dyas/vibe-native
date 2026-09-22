"""Agreement of the clean-room key detector (vibenative.tonality) with the reference
labels in oracle/index.json, per profile set, in MIREX categories.

    python tools/eval_key.py            # all profile sets x front-end variants
    python tools/eval_key.py --loo      # also leave-one-out corpus-fitted profiles

Global PCPs are cached in oracle/pcp_cache.npz (keyed by track hash + variant)
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
from vibenative.paths import wsl_to_windows  # noqa: E402

ORACLE = ROOT / "oracle"
CACHE = ORACLE / "pcp_cache.npz"
# name -> pcp_from_magnitudes() kwargs. Every variant shares one decode + FFT per track.
# "default" is what the app ships; add entries here to sweep a setting.
VARIANTS: dict[str, dict] = {"default": {}}


def load_index() -> dict:
    return json.loads((ORACLE / "index.json").read_text(encoding="utf-8"))


def load_pcps(index: dict, verbose: bool = True) -> dict[tuple[str, str], np.ndarray]:
    """{(hash, variant): pcp} for every track with audio on disk, via the cache."""
    cache: dict[str, np.ndarray] = {}
    if CACHE.exists():
        with np.load(CACHE) as z:
            cache = {k: z[k] for k in z.files}
    out = {}
    for i, h in enumerate(sorted(index)):
        path = Path(wsl_to_windows(index[h]["file"]))
        if not path.exists():
            continue
        missing = [n for n in VARIANTS if f"{h}:{n}" not in cache]
        if missing:
            if verbose:
                print(f"[{i + 1}/{len(index)}] {path.name}".encode("ascii", "replace").decode(), flush=True)
            audio = decode_mono(path, tonality.SR)
            for frame in sorted({VARIANTS[n].get("frame", tonality.FRAME) for n in missing}):
                mags, freqs = tonality.magnitudes(audio, tonality.SR, frame)
                for n in missing:
                    settings = {k: v for k, v in VARIANTS[n].items() if k != "frame"}
                    if VARIANTS[n].get("frame", tonality.FRAME) == frame:
                        cache[f"{h}:{n}"] = tonality.pcp_from_magnitudes(mags, freqs, **settings)
            np.savez(CACHE, **cache)  # save as we go: decoding is the slow part
        for n in VARIANTS:
            out[(h, n)] = cache[f"{h}:{n}"]
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


def report(label: str, cats: Counter) -> None:
    n = sum(cats.values())
    mirex = (cats["exact"] + 0.5 * cats["fifth"] + 0.3 * cats["relative"] + 0.2 * cats["parallel"]) / n
    parts = "  ".join(f"{c}={cats[c]}" for c in ("exact", "fifth", "relative", "parallel", "other"))
    print(f"{label:<14} exact {cats['exact']:>3}/{n} ({100 * cats['exact'] / n:5.1f}%)  mirex {mirex:.3f}   {parts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loo", action="store_true", help="also score leave-one-out fitted profiles")
    args = ap.parse_args()

    index = load_index()
    pcps = load_pcps(index)
    n = len({h for h, _ in pcps})
    print(f"\n{n} tracks with audio\n")
    for variant in VARIANTS:
        print(variant)
        for name in sorted(tonality.PROFILES):
            report(f"  {name}", evaluate(pcps, index, variant, profile=name))
        if args.loo:
            report("  fitted LOO", evaluate(pcps, index, variant, loo=True))
        print()


if __name__ == "__main__":
    main()

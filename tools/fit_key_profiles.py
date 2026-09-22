"""Derive the ``edm`` key profiles from labelled audio (Faraldo 2017 §3.1: per-mode
median of the tonic-rotated global PCP) and write them to
src/vibenative/data/key_profiles.json, which vibenative.tonality loads at import.

    python tools/fit_key_profiles.py                 # fit from oracle/index.json labels
    python tools/fit_key_profiles.py --variant NAME   # a sweep entry from eval_key.VARIANTS

The fitted vectors are statistics of our own audio + labels; provenance (label
source, track count, front-end settings, date) is recorded alongside them.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import eval_key  # noqa: E402
from vibenative import tonality  # noqa: E402

OUT = ROOT / "src" / "vibenative" / "data" / "key_profiles.json"
DEFAULT_VARIANT = "default"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default=DEFAULT_VARIANT, help="front-end variant name from eval_key.VARIANTS")
    args = ap.parse_args()
    if args.variant not in eval_key.VARIANTS:
        sys.exit(f"unknown variant {args.variant!r}; one of: {list(eval_key.VARIANTS)}")

    index = eval_key.load_index()
    pcps = eval_key.load_pcps(index)
    hashes = [h for h in sorted(index) if (h, args.variant) in pcps]
    profiles = eval_key.fit_profiles(pcps, index, hashes, args.variant)
    loo = eval_key.evaluate(pcps, index, args.variant, loo=True)

    doc = {
        "about": "Corpus-derived key profiles (per-mode median of tonic-rotated global PCPs, "
                 "after Faraldo et al. 2017). Index 0 = tonic, ascending semitones. "
                 "Fitted by tools/fit_key_profiles.py from this project's own audio and labels.",
        "fitted": date.today().isoformat(),
        "tracks": len(hashes),
        "labels": "oracle/index.json",
        "front_end": {
            "frame": tonality.FRAME, "hop": tonality.HOP, "f_lo": tonality.F_LO, "f_hi": tonality.F_HI,
            "top_peaks": tonality.TOP_PEAKS, "peak_floor": tonality.PEAK_FLOOR, "power": tonality.POWER,
            "gamma": tonality.GAMMA, "subharmonics": tonality.SUBHARMONICS, "frame_norm": True,
            "overrides": eval_key.VARIANTS[args.variant],
        },
        "leave_one_out": {k: loo[k] for k in ("exact", "fifth", "relative", "parallel", "other")},
        "profiles": {"edm": {m: [round(float(x), 4) for x in v] for m, v in profiles.items()}},
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    eval_key.report("fitted LOO", loo)
    for m, v in profiles.items():
        print(f"{m:<6}", np.round(v, 3))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

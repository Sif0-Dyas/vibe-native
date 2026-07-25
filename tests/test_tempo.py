"""Phase-3 acceptance: TempoCNN BPM vs the oracle.

For each track: decode at 11025 Hz and run tempo.estimate, then require the BPM to
be within 2% of the oracle OR a half/double multiple. Acceptance: >= 95% of tracks.
Deterministic ~40-track subset by default; VIBE_FULL_ORACLE=1 runs all 121. Skips
on a clone lacking oracle audio / the converted TempoCNN model.
"""

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "oracle"


def _subset(index):
    keys = sorted(index)
    return keys if os.environ.get("VIBE_FULL_ORACLE") else keys[::3]


def _ready():
    if not (ORACLE / "index.json").exists() or not (ROOT / "models" / "tempocnn.onnx").exists():
        return False, "need oracle/ + models/tempocnn.onnx"
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from vibenative.paths import wsl_to_windows

    idx = json.loads((ORACLE / "index.json").read_text())
    for h in _subset(idx):
        if not Path(wsl_to_windows(idx[h]["file"])).exists():
            return False, "oracle audio not on disk"
    return True, ""


_READY, _WHY = _ready()


def _within(bpm, oref):
    return oref is None or any(abs(bpm - c) / c <= 0.02 for c in (oref, oref / 2, oref * 2))


@pytest.mark.skipif(not _READY, reason=_WHY)
def test_tempo_matches_oracle():
    from vibenative import tempo
    from vibenative.decode import decode_mono
    from vibenative.paths import wsl_to_windows

    index = json.loads((ORACLE / "index.json").read_text())
    keys = _subset(index)
    fails = []
    for h in keys:
        m = index[h]
        bpm, _ = tempo.estimate(decode_mono(wsl_to_windows(m["file"]), 11025), 11025)
        if not _within(bpm, m["bpm"]):
            fails.append(f"{Path(m['file']).name}: native {bpm} vs oracle {m['bpm']}")

    rate = 1.0 - len(fails) / len(keys)
    assert rate >= 0.95, (
        f"tempo within 2%/octave for only {rate:.1%} (< 95%); {len(fails)} misses:\n"
        + "\n".join(fails[:15])
    )

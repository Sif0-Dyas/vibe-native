"""Phase-3 acceptance: native key estimation vs the oracle.

For each track: decode at 44100 Hz and run key.estimate, then require an EXACT
(key, scale) match against the oracle (Essentia KeyExtractor). Acceptance: >= 90%
of tracks. Deterministic ~40-track subset by default; VIBE_FULL_ORACLE=1 runs all
121 (observed 121/121 = 100%). Skips on a clone lacking oracle audio.

The native pipeline (src/vibenative/key.py) is a stage-for-stage port of
Essentia's KeyExtractor (Windowing/Spectrum/SpectralPeaks/SpectralWhitening/HPCP/
Key), validated against per-stage dumps from the WSL Essentia install.
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
    if not (ORACLE / "index.json").exists():
        return False, "need oracle/index.json"
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from vibenative.paths import wsl_to_windows

    idx = json.loads((ORACLE / "index.json").read_text())
    for h in _subset(idx):
        if not Path(wsl_to_windows(idx[h]["file"])).exists():
            return False, "oracle audio not on disk"
    return True, ""


_READY, _WHY = _ready()


@pytest.mark.skipif(not _READY, reason=_WHY)
def test_key_matches_oracle():
    from vibenative import key
    from vibenative.paths import wsl_to_windows

    index = json.loads((ORACLE / "index.json").read_text())
    keys = _subset(index)
    fails = []
    for h in keys:
        m = index[h]
        k, scale, _ = key.estimate_file(wsl_to_windows(m["file"]))
        if (k, scale) != (m["key"], m["scale"]):
            fails.append(
                f"{Path(m['file']).name}: native {k} {scale} vs oracle {m['key']} {m['scale']}"
            )

    rate = 1.0 - len(fails) / len(keys)
    assert rate >= 0.90, (
        f"exact key+scale match for only {rate:.1%} (< 90%); {len(fails)} misses:\n"
        + "\n".join(fails[:15])
    )

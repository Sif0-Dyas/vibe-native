"""Phase-2 acceptance: native embeddings vs the WSL oracle.

For each oracle track: decode the source file natively (ffmpeg -> mono -> 16 kHz,
matching Essentia MonoLoader) and run the native mel frontend + EffNet embedder,
then assert (a) frame counts match, (b) per-track cosine(native mean, oracle
emb_mean) > 0.999, and (c) mean per-frame cosine > 0.999.

A deterministic ~40-track SUBSET runs by default (fast inner loop); set
VIBE_FULL_ORACLE=1 to run all 121 as the final gate. Skips with a clear reason on
a clone without the oracle audio / converted models.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "oracle"
THRESH = 0.999


def _subset(index):
    """Deterministic ~40 of the 121 tracks (every 3rd hash, sorted)."""
    keys = sorted(index)
    return keys if os.environ.get("VIBE_FULL_ORACLE") else keys[::3]


def _audio_ready():
    if not (ORACLE / "index.json").exists() or not (ROOT / "models" / "effnet.onnx").exists():
        return False, "need oracle/ + models/effnet.onnx (Phase 0/1)"
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from vibenative.legacy import wsl_to_windows

    index = json.loads((ORACLE / "index.json").read_text())
    for h in _subset(index):
        if not Path(wsl_to_windows(index[h]["file"])).exists():
            return False, "oracle audio not on disk (source tracks moved/absent)"
    return True, ""


_READY, _WHY = _audio_ready()


def _cos(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


@pytest.mark.skipif(not _READY, reason=_WHY)
def test_embeddings_match_oracle():
    from vibenative.decode import decode_16k_mono
    from vibenative.legacy import wsl_to_windows
    from vibenative.onnx_engine import get_engine

    embedder = get_engine()["embedder"]
    index = json.loads((ORACLE / "index.json").read_text())
    keys = _subset(index)

    fails, sims = [], []
    for h in keys:
        meta = index[h]
        ref = np.load(ORACLE / f"{h}.npz")
        oemb, omean = ref["embeddings"], ref["emb_mean"]
        native = embedder(decode_16k_mono(wsl_to_windows(meta["file"])))
        name = Path(meta["file"]).name

        if native.shape[0] != oemb.shape[0]:
            fails.append(f"{name}: frame count {native.shape[0]} != {oemb.shape[0]}")
            continue
        mean_c = _cos(native.mean(0), omean)
        pf = float(np.mean([_cos(native[i], oemb[i]) for i in range(oemb.shape[0])]))
        sims.append(min(mean_c, pf))
        if mean_c < THRESH or pf < THRESH:
            fails.append(f"{name}: mean-emb {mean_c:.5f}, per-frame {pf:.5f} (< {THRESH})")

    assert len(keys) >= 40 or os.environ.get("VIBE_FULL_ORACLE"), f"subset too small: {len(keys)}"
    assert not fails, (
        f"{len(fails)}/{len(keys)} tracks below cos {THRESH} "
        f"(min {min(sims) if sims else float('nan'):.5f}):\n" + "\n".join(fails[:15])
    )

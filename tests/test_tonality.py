"""The clean-room key detector (vibenative.tonality).

Synthetic cases run everywhere: chord progressions built from harmonic tones must
land on the key they were written in, for every built-in profile set, whether or
not the track is tuned to A440. The oracle-agreement test needs the oracle audio
and is a soft bar (the detector is an independent implementation, not a port; see
docs/KEY_SPEC.md).
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from vibenative import tonality

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "oracle"
SR = tonality.SR


def _tone(midi, seconds=1.5, partials=6, detune=0.0):
    t = np.arange(int(SR * seconds)) / SR
    f = 440.0 * 2 ** ((midi + detune - 69) / 12)
    return sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, partials + 1))


def _progression(chords, detune=0.0):
    x = np.concatenate([sum(_tone(m, detune=detune) for m in ch) for ch in chords])
    return (0.1 * x).astype(np.float32)


# I IV V I in C major; i iv V i in A minor (octave 4)
C_MAJOR = [(60, 64, 67), (65, 69, 72), (67, 71, 74), (60, 64, 67)]
A_MINOR = [(57, 60, 64), (62, 65, 69), (64, 68, 71), (57, 60, 64)]


@pytest.mark.parametrize("profile", sorted(tonality.PROFILES))
def test_synthetic_major_and_minor(profile):
    k, s, r = tonality.estimate(_progression(C_MAJOR), SR, profile)
    assert (k, s) == ("C", "major"), (k, s, r)
    k, s, r = tonality.estimate(_progression(A_MINOR), SR, profile)
    assert (k, s) == ("A", "minor"), (k, s, r)


def test_transposition_and_naming():
    up = [tuple(m + 3 for m in ch) for ch in A_MINOR]  # C minor
    assert tonality.estimate(_progression(up), SR)[:2] == ("C", "minor")
    up = [tuple(m + 6 for m in ch) for ch in A_MINOR]  # Eb minor — flat spelling
    assert tonality.estimate(_progression(up), SR)[:2] == ("Eb", "minor")


def test_tuning_correction_handles_detuned_track():
    # a quarter-tone flat is the worst case for a fixed A440 grid
    x = _progression(C_MAJOR, detune=-0.4)
    mags, freqs = tonality.magnitudes(x, SR)
    assert abs(tonality._tuning_offset(tonality.emphasise(mags, freqs), freqs) + 0.4) < 0.1
    assert tonality.estimate(x, SR)[:2] == ("C", "major")


def test_silence_and_short_input_do_not_crash():
    k, s, r = tonality.estimate(np.zeros(SR, dtype=np.float32), SR)
    assert s in tonality.MODES and r == 0.0
    k, s, r = tonality.estimate(np.zeros(100, dtype=np.float32), SR)
    assert s in tonality.MODES


def test_strength_is_a_correlation():
    _, _, r = tonality.estimate(_progression(C_MAJOR), SR)
    assert 0.5 < r <= 1.0


def _oracle_ready():
    if not (ORACLE / "index.json").exists():
        return False, "need oracle/index.json"
    from vibenative.paths import wsl_to_windows

    idx = json.loads((ORACLE / "index.json").read_text())
    keys = sorted(idx)
    keys = keys if os.environ.get("VIBE_FULL_ORACLE") else keys[::3]
    if not all(Path(wsl_to_windows(idx[h]["file"])).exists() for h in keys):
        return False, "oracle audio not on disk"
    return True, ""


_READY, _WHY = _oracle_ready()


@pytest.mark.skipif(not _READY, reason=_WHY)
def test_oracle_agreement():
    """Agreement with the reference labels. The bar is deliberately below the old
    port's 100 % — these are Essentia's labels, not ground truth, and this is a
    different algorithm; the number to watch is tools/eval_key.py."""
    from vibenative.paths import wsl_to_windows

    idx = json.loads((ORACLE / "index.json").read_text())
    keys = sorted(idx)
    keys = keys if os.environ.get("VIBE_FULL_ORACLE") else keys[::3]
    hits = sum(
        tonality.estimate_file(wsl_to_windows(idx[h]["file"]))[:2] == (idx[h]["key"], idx[h]["scale"])
        for h in keys
    )
    assert hits / len(keys) >= 0.60, f"{hits}/{len(keys)} exact"

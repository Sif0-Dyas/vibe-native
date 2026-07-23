"""Musical key via chroma-profile correlation. Contract (Phase 3):

    estimate(audio: np.ndarray, sr: int) -> (key: str, scale: str, strength: float)

Matches Essentia KeyExtractor's approach in structure: a 12-bin chroma correlated
against the 'bgate' major/minor profiles (KeyExtractor's default profileType,
verbatim from src/algorithms/tonal/key.cpp) at all 12 rotations via Pearson
correlation; the best (rotation, mode) gives key + scale. KeyExtractor defaults:
44100 Hz, frameSize/hopSize 4096, tuning 440, minFreq 25, maxFreq 3500.

STATUS (Phase 3): BELOW the 90% acceptance -- this is a documented scaffold, not
done. Diagnosis (stage-by-stage vs Essentia): the profile-correlation FRAMEWORK
is not sufficient on its own. Feeding Essentia's OWN averaged HPCP (bin 0 = A, so
tonic maps with +9) through this bgate-Pearson correlation reproduces only ~55% of
KeyExtractor's oracle decisions -- so KeyExtractor's Key algorithm does more than a
profile correlation on the mean HPCP (relative-strength tie-breaks, its specific
HPCP config: weightType/harmonics/bandPreset/nonLinear, etc.). Reaching 90% needs
a faithful port of Essentia's HPCP (with KeyExtractor's params) + Key.cpp, which is
a focused sub-task. This simple spectral chroma alone scores ~30%.
"""

import numpy as np

SR = 44100
FRAME, HOP = 4096, 4096  # KeyExtractor: non-overlapping
FMIN, FMAX = 25.0, 3500.0
TUNING = 440.0
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Essentia Key 'bgate' profiles (index 0 = tonic), from src/algorithms/tonal/key.cpp
BGATE_MAJOR = np.array([1.00, 0.00, 0.42, 0.00, 0.53, 0.37, 0.00, 0.77, 0.00, 0.38, 0.21, 0.30])
BGATE_MINOR = np.array([1.00, 0.00, 0.36, 0.39, 0.00, 0.38, 0.00, 0.74, 0.27, 0.00, 0.42, 0.23])

_freqs = np.fft.rfftfreq(FRAME, 1.0 / SR)
_band = (_freqs >= FMIN) & (_freqs <= FMAX)
with np.errstate(divide="ignore"):
    _midi = 69.0 + 12.0 * np.log2(np.where(_freqs > 0, _freqs, 1.0) / TUNING)
_pc = (np.rint(_midi).astype(np.int64) + 1200) % 12  # A440 -> pitch class 9
_HANN = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FRAME) / FRAME)).astype(np.float64)


def _resample(x, sr):
    if sr == SR:
        return x.astype(np.float64)
    x = x.astype(np.float64)
    n = int(round(len(x) * SR / sr))
    pos = np.arange(n) * (sr / SR)
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(x) - 1)
    frac = pos - np.floor(pos)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    return (1 - frac) * x[i0] + frac * x[i1]


def _chroma(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64)
    if len(x) < FRAME:
        return np.zeros(12)
    n = (len(x) - FRAME) // HOP + 1
    frames = x[HOP * np.arange(n)[:, None] + np.arange(FRAME)[None, :]]
    mag = np.abs(np.fft.rfft(frames * _HANN, axis=1))
    energy = (mag[:, _band] ** 2).sum(axis=0)  # per in-band bin, summed over frames
    chroma = np.bincount(_pc[_band], weights=energy, minlength=12).astype(np.float64)
    m = chroma.max()
    return chroma / m if m > 0 else chroma


def _pearson(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def estimate(audio: np.ndarray, sr: int) -> tuple[str, str, float]:
    chroma = _chroma(_resample(audio, sr))
    best_r, best_key, best_scale = -2.0, "C", "major"
    for scale, prof in (("major", BGATE_MAJOR), ("minor", BGATE_MINOR)):
        for tonic in range(12):
            r = _pearson(chroma, np.roll(prof, tonic))  # tonic at pitch class `tonic`
            if r > best_r:
                best_r, best_key, best_scale = r, NOTES[tonic], scale
    return best_key, best_scale, round(best_r, 4)

"""Global musical key of a track: pitch-class profile + template matching.

Implemented from docs/KEY_SPEC.md only (Krumhansl & Kessler 1982, Temperley 1999,
Gómez 2006, Faraldo et al. 2016/2017, Müller 2015). This is an independent,
MIT-licensed implementation — it is NOT derived from Essentia and does not try to
match it stage-for-stage. Pure numpy; no scipy/librosa so the frozen build stays
small.

Public API mirrors the previous module: ``estimate(audio, sr) -> (key, scale,
strength)`` and ``estimate_file(path)``. ``pcp(audio, sr)`` exposes the global
pitch-class profile so tools/fit_key_profiles.py can derive corpus profiles.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SR = 44100
FRAME = 8192
HOP = 4096
F_LO = 15.0  # high-pass: drops kick/sub thump; the bassline's partials survive
F_HI = 5000.0
F_MIN = 15.0  # lowest bin kept by ``magnitudes`` (so tools can sweep F_LO downward)
GAMMA = 0.0  # log-compression strength; 0 = linear magnitudes
POWER = 1.0  # magnitude exponent
PEAK_FLOOR = 0.01  # spectral peaks below this fraction of the frame max are ignored
TOP_PEAKS = 150  # strongest peaks kept per frame; the rest of the maxima are noise
SUBHARMONICS = 0  # a peak at f also credits f/2 .. f/(SUBHARMONICS+1)
DECAY = 1.0  # sub-harmonic weight = DECAY^(h-1) / h
BASS_LO = 25.0  # the bass band starts here regardless of F_LO
BASS_HI = 250.0  # the bass band: its own PCP is a strong tonic cue in EDM
BASS_PEAKS = 4  # peaks kept per frame in the bass band (a bassline is one or two notes)
BASS_WEIGHT = 0.0  # share of the bass-band PCP in the final profile (0 = full band only)
GATE = 0.2  # PCP bins under this (after max-normalisation) are zeroed
SILENCE_RMS = 1e-4
TUNING_BIN = 0.05  # semitones (5 cents)
TUNING_F_LO = 500.0  # tuning is estimated from peaks above this only
TUNING_PROMINENCE = 2.0  # histogram mode must be this × the mean bin to be believed

KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MODES = ("major", "minor")

# Published profiles (index 0 = tonic, ascending semitones).
PROFILES: dict[str, dict[str, np.ndarray]] = {
    # Krumhansl & Kessler (1982), probe-tone ratings.
    "kk": {
        "major": np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
        "minor": np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
    },
    # Temperley (1999), "What's key for key?".
    "temperley": {
        "major": np.array([5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]),
        "minor": np.array([5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]),
    },
}

_DATA = Path(__file__).resolve().parent / "data" / "key_profiles.json"

# The trained model (tools/train_key_templates.py): a linear scorer over the
# concatenated, per-block standardised PCPs of several frequency bands.
#   score(t, m) = logsumexp_k(<standardise(pcp) rolled by t, W[m][k]> + bias[m][k])
# {"blocks": [pcp_from_magnitudes kwargs, ...],       # one PCP per frequency band
#  "weights": {mode: [[12*len(blocks)], ...]},        # one or more sub-templates per mode
#  "bias":    {mode: [float, ...]}}
MODEL: dict | None = None


def _load_fitted() -> None:
    """Corpus-derived profiles and/or the trained multi-band model, if present."""
    global MODEL
    if not _DATA.exists():
        return
    try:
        doc = json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for name, modes in doc.get("profiles", {}).items():
        try:
            PROFILES[name] = {m: np.asarray(modes[m], dtype=np.float64) for m in MODES}
        except (KeyError, TypeError, ValueError):
            continue
    model = doc.get("model")
    if model:
        try:
            MODEL = {
                "blocks": [dict(b) for b in model["blocks"]],
                # weights[mode]: (K, 12 * n_blocks), bias[mode]: (K,)
                "weights": {m: np.atleast_2d(np.asarray(model["weights"][m], dtype=np.float64)) for m in MODES},
                "bias": {m: np.atleast_1d(np.asarray(model["bias"][m], dtype=np.float64)) for m in MODES},
            }
            assert all(MODEL["weights"][m].shape[1] == 12 * len(MODEL["blocks"])
                       and MODEL["weights"][m].shape[0] == MODEL["bias"][m].size for m in MODES)
        except (KeyError, TypeError, ValueError, AssertionError):
            MODEL = None


_load_fitted()

DEFAULT_PROFILE = "model" if MODEL else ("edm" if "edm" in PROFILES else "temperley")


# --- spectral front end -----------------------------------------------------------


def _frames(audio: np.ndarray, frame: int = FRAME, hop: int = HOP) -> np.ndarray:
    """(n_frames, frame) view of the signal; pads the tail so short clips still
    yield one frame."""
    x = np.asarray(audio, dtype=np.float32).ravel()
    if x.size < frame:
        x = np.pad(x, (0, frame - x.size))
    n = 1 + (x.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def magnitudes(audio: np.ndarray, sr: int = SR, frame: int = FRAME, hop: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame max-normalised magnitude spectra of the non-silent frames,
    restricted to [F_LO, F_HI]. Returns (mags (n, bins), bin_freqs (bins,)).
    Separate from ``emphasise`` so tools can sweep settings on one FFT pass."""
    fr = _frames(audio, frame, hop or frame // 2)
    rms = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1))
    fr = fr[rms > SILENCE_RMS]
    if fr.shape[0] == 0:
        return np.zeros((0, 0)), np.zeros(0)
    win = np.hanning(frame + 1)[:-1].astype(np.float32)  # periodic Hann
    mag = np.abs(np.fft.rfft(fr * win, axis=1))
    freqs = np.fft.rfftfreq(frame, 1.0 / sr)
    keep = (freqs >= F_MIN) & (freqs <= F_HI)
    mag = mag[:, keep]
    top = mag.max(axis=1, keepdims=True)
    top[top == 0] = 1.0
    return (mag / top).astype(np.float32), freqs[keep]


def emphasise(mag: np.ndarray, freqs: np.ndarray, f_lo: float = F_LO, gamma: float = GAMMA,
              peaks: bool = True, peak_floor: float = PEAK_FLOOR, top_peaks: int = TOP_PEAKS,
              power: float = POWER, f_hi: float = F_HI) -> np.ndarray:
    """What of the spectrum counts as pitch evidence. Bins below ``f_lo`` are
    dropped. With ``peaks`` only local maxima survive, and of those only the
    ``top_peaks`` strongest per frame above ``peak_floor`` x the frame max
    (Gómez 2006: pitch content lives in a few strong peaks; a noisy spectrum has a
    local maximum every few bins). ``power`` sharpens (>1) or flattens (<1) the
    dynamic range; ``gamma`` > 0 applies log(1 + gamma·m)."""
    if mag.size == 0:
        return mag
    mag = np.where((freqs[None, :] >= f_lo) & (freqs[None, :] <= f_hi), mag, 0.0)
    if peaks:
        inner = mag[:, 1:-1]
        is_peak = (inner > mag[:, :-2]) & (inner >= mag[:, 2:]) & (inner >= peak_floor)
        mag = np.pad(np.where(is_peak, inner, 0.0), ((0, 0), (1, 1)))
        if top_peaks and top_peaks < mag.shape[1]:
            cut = -np.partition(-mag, top_peaks, axis=1)[:, top_peaks - 1: top_peaks]  # N-th largest
            mag = np.where(mag >= cut, mag, 0.0)
    if power != 1.0:
        mag = mag ** power
    return np.log1p(gamma * mag) if gamma > 0 else mag


def _tuning_offset(mags: np.ndarray, freqs: np.ndarray, enabled: bool = True) -> float:
    """Global deviation from A440 in semitones, from the histogram of spectral-peak
    pitch fractions (Müller 2015 §3.1). Only peaks above TUNING_F_LO count — below
    that a bin is wider than the tuning resolution — and the histogram mode must
    stand out from the average bin by TUNING_PROMINENCE, else the track is taken
    as A440 (a flat histogram means noise, not a detuned track)."""
    if mags.size == 0 or not enabled:
        return 0.0
    band = freqs >= TUNING_F_LO
    if band.sum() < 3:
        return 0.0
    m = mags[:, band]
    pitch = 69.0 + 12.0 * np.log2(freqs[band] / 440.0)
    frac = pitch - np.round(pitch)  # [-0.5, 0.5)
    inner = m[:, 1:-1]
    is_peak = (inner > m[:, :-2]) & (inner >= m[:, 2:])
    weights = np.where(is_peak, inner, 0.0).sum(axis=0)  # per bin, summed over frames
    if not np.any(weights):
        return 0.0
    nb = int(round(1.0 / TUNING_BIN)) | 1  # odd, so one bin is centred on 0 (in tune)
    edges = np.linspace(-0.5, 0.5, nb + 1)
    hist, _ = np.histogram(frac[1:-1], bins=edges, weights=weights)
    if hist.max() < TUNING_PROMINENCE * hist.mean():
        return 0.0
    centre = 0.5 * (edges[:-1] + edges[1:])
    return float(centre[int(np.argmax(hist))])


def _chroma_matrix(freqs: np.ndarray, offset: float, subharmonics: int, decay: float = DECAY) -> np.ndarray:
    """(bins, 12) weights mapping spectral bins to pitch classes. Each bin lands on
    the semitone nearest its (tuning-corrected) pitch, with a cos² taper on the
    distance to the semitone centre. With subharmonics > 0 the bin also credits
    f/2 .. f/(subharmonics+1) with weight decay^(h-1)/h, so a partial that is
    really the 3rd harmonic of a lower note (a fifth up) credits that note."""
    m = np.zeros((freqs.size, 12))
    for h in range(1, subharmonics + 2):
        pitch = 69.0 + 12.0 * np.log2(freqs / (440.0 * h)) - offset
        nearest = np.round(pitch)
        w = np.cos(np.pi * (pitch - nearest)) ** 2 * decay ** (h - 1) / h
        pc = (nearest.astype(int) % 12)
        np.add.at(m, (np.arange(freqs.size), pc), w)
    return m


def _section(mags: np.ndarray, which: str, frac: float) -> np.ndarray:
    """A contiguous run of ``frac`` of the frames: the loudest such window
    ("loud", typically the drop) or the quietest ("quiet", the breakdown). EDM
    sections often disagree about the key, so a model can weigh them apart."""
    n = mags.shape[0]
    w = max(1, int(round(n * frac)))
    if w >= n:
        return mags
    energy = mags.sum(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(energy)])
    window = csum[w:] - csum[:-w]  # energy of each contiguous w-frame window
    start = int(np.argmax(window) if which == "loud" else np.argmin(window))
    return mags[start:start + w]


def _global_pcp(mags: np.ndarray, chroma_matrix: np.ndarray, frame_norm: bool) -> np.ndarray:
    chroma = mags @ chroma_matrix  # (frames, 12)
    if frame_norm:
        top = chroma.max(axis=1, keepdims=True)
        chroma = chroma / np.where(top > 0, top, 1.0)
    g = chroma.mean(axis=0)
    top = g.max()
    return g / top if top > 0 else g


def pcp_from_magnitudes(mags: np.ndarray, freqs: np.ndarray, subharmonics: int = SUBHARMONICS,
                        decay: float = DECAY, f_lo: float = F_LO, gamma: float = GAMMA, peaks: bool = True,
                        peak_floor: float = PEAK_FLOOR, top_peaks: int = TOP_PEAKS, power: float = POWER,
                        frame_norm: bool = True, tuning: bool = True, bass_weight: float = BASS_WEIGHT,
                        bass_hi: float = BASS_HI, bass_peaks: int = BASS_PEAKS, f_hi: float = F_HI,
                        offset: float | None = None, section: str | None = None,
                        section_frac: float = 0.25) -> np.ndarray:
    """Global PCP. With ``bass_weight`` > 0 the profile is a blend of the
    full-band PCP and a PCP of the bass band alone (few peaks per frame, so it
    tracks the bassline's root notes): bass chroma is the strongest tonic cue in
    EDM, where the upper voices are often modally ambiguous (Mauch & Dixon 2010
    use a separate bass chroma for the same reason in chord recognition)."""
    if mags.size == 0:
        return np.zeros(12)
    if section:
        mags = _section(mags, section, section_frac)
    full = emphasise(mags, freqs, f_lo, gamma, peaks, peak_floor, top_peaks, power, f_hi)
    if offset is None:
        offset = _tuning_offset(full, freqs, tuning)
    cm = _chroma_matrix(freqs, offset, subharmonics, decay)
    g = _global_pcp(full, cm, frame_norm)
    if bass_weight > 0:
        bass = emphasise(mags, freqs, BASS_LO, gamma, peaks, peak_floor, bass_peaks, power, f_hi=bass_hi)
        gb = _global_pcp(bass, _chroma_matrix(freqs, offset, 0), frame_norm)
        g = (1.0 - bass_weight) * g + bass_weight * gb
        g = g / g.max() if g.max() > 0 else g
    return g


def pcp(audio: np.ndarray, sr: int = SR, frame: int = FRAME, **settings) -> np.ndarray:
    """Global 12-bin pitch-class profile (C..B), max-normalised, NOT gated —
    callers that fit profiles want the raw shape; ``estimate`` gates it."""
    mags, freqs = magnitudes(audio, sr, frame)
    return pcp_from_magnitudes(mags, freqs, **settings)


# --- template matching ------------------------------------------------------------


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def _standardise(v: np.ndarray) -> np.ndarray:
    """Zero-mean, unit-norm per 12-bin block (so a dot product is a correlation)."""
    out = np.array(v, dtype=np.float64)
    for j in range(0, out.size, 12):
        blk = out[j:j + 12] - out[j:j + 12].mean()
        n = np.linalg.norm(blk)
        out[j:j + 12] = blk / n if n > 0 else blk
    return out


def features(mags: np.ndarray, freqs: np.ndarray, blocks: list[dict] | None = None) -> np.ndarray:
    """Concatenated, gated PCPs of the model's frequency-band blocks (12 each)."""
    blocks = MODEL["blocks"] if blocks is None and MODEL else (blocks or [{}])
    parts = []
    for kw in blocks:
        g = pcp_from_magnitudes(mags, freqs, **kw)
        parts.append(np.where(g < GATE, 0.0, g))
    return np.concatenate(parts)


def match_model(feature: np.ndarray, model: dict | None = None) -> tuple[str, str, float]:
    """Best key under the trained linear model. Strength is the softmax
    probability of the winner over all 24 keys (0..1)."""
    model = model or MODEL
    if not np.any(feature):
        return KEY_NAMES[0], "minor", 0.0  # silence: no evidence at all
    x = _standardise(feature)
    nblk = x.size // 12
    scores = np.empty((12, 2))
    for t in range(12):
        rolled = np.concatenate([np.roll(x[j * 12:(j + 1) * 12], -t) for j in range(nblk)])
        for mi, m in enumerate(MODES):
            sub = model["weights"][m] @ rolled + model["bias"][m]  # one score per sub-template
            top = sub.max()
            scores[t, mi] = top + np.log(np.exp(sub - top).sum())  # soft max over sub-templates
    flat = scores.ravel()
    best = int(np.argmax(flat))
    p = np.exp(flat - flat[best])
    return KEY_NAMES[best // 2], MODES[best % 2], float(1.0 / p.sum())


def match(profile_vec: np.ndarray, profile: str = DEFAULT_PROFILE) -> tuple[str, str, float]:
    """Best (key, mode, strength). With ``profile="model"`` ``profile_vec`` is the
    multi-band feature vector from ``features``; otherwise it is a single 12-bin
    PCP correlated against the named 12-bin templates (ties go to minor)."""
    if profile == "model":
        return match_model(profile_vec)
    templates = PROFILES[profile]
    best = ("C", "minor", -2.0)
    for mode in ("minor", "major"):  # minor first so a tie keeps minor
        t = templates[mode]
        for tonic in range(12):
            r = _pearson(profile_vec[:12], np.roll(t, tonic))
            if r > best[2]:
                best = (KEY_NAMES[tonic], mode, r)
    return best


def estimate(audio: np.ndarray, sr: int = SR, profile: str = DEFAULT_PROFILE, **front_end) -> tuple[str, str, float]:
    """(key, "major"|"minor", strength) for a mono signal. With the trained model
    (the default when data/key_profiles.json carries one) strength is a
    probability; with a named profile set it is a Pearson correlation and
    ``front_end`` kwargs go to ``pcp``."""
    if profile == "model" and MODEL:
        mags, freqs = magnitudes(audio, sr)
        return match_model(features(mags, freqs))
    if profile == "model":
        profile = "edm" if "edm" in PROFILES else "temperley"
    g = pcp(audio, sr, **front_end)
    g = np.where(g < GATE, 0.0, g)
    return match(g, profile)


def estimate_file(path, profile: str = DEFAULT_PROFILE) -> tuple[str, str, float]:
    from .decode import decode_mono

    return estimate(decode_mono(path, SR), SR, profile)

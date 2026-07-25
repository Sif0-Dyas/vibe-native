"""Musical key via a faithful native port of Essentia's KeyExtractor pipeline.

    estimate(audio: np.ndarray, sr: int) -> (key: str, scale: str, strength: float)

STATUS (Phase 3): PASSED -- exact (key, scale) match on 121/121 oracle tracks
(100%, acceptance was >= 90%). No profile/scale hacks: the pipeline reproduces
Essentia's mean HPCP to cosine ~1.0, and the proven Key correlation does the rest.

This is a numpy re-implementation of Essentia's `KeyExtractor`, ported
stage-for-stage from the C++ source (essentia 2.1-beta6) and validated against
dumps from the WSL Essentia install (the "Phase-2 playbook"). KeyExtractor's
exact configuration (keyextractor.cpp):

    Windowing(hann, size 4096)
      -> Spectrum(size 4096)                      -> |rfft|, 2049 bins
      -> SpectralPeaks(magnitudeThreshold 0.0001, minFrequency 25,
                       maxFrequency 3500, maxPeaks 60, orderBy magnitude)
      -> SpectralWhitening(maxFrequency 3500)
      -> HPCP(size 12, referenceFrequency 440, minFrequency 25,
              maxFrequency 3500, harmonics 4, weightType cosine,
              windowSize 1.0, bandPreset false, nonLinear false,
              normalized none, maxShifted false)
      -> mean over frames
      -> Key(profileType bgate, usePolyphony false, useThreeChords false,
             numHarmonics 4, slope 0.6)

Ports (each verbatim from the algorithm source):
  * `_peak_detection`  -- standard/peakdetection.cpp compute() + interpolate()
  * `_spectral_whitening` -- spectral/spectralwhitening.cpp compute()
  * `_hpcp`            -- spectral/hpcp.cpp compute()/addContribution()
  * `_key_from_pcp`    -- tonal/key.cpp compute()/correlation()

Key facts established while porting:
  * HPCP bin 0 = 440 Hz = A; keyNames use flats ["A","Bb",...,"Ab"] (key.cpp).
  * With size-12 HPCP and usePolyphony=false, Key uses the RAW bgate profiles
    (the resize() harmonic-interpolation loop `for j in 1..n-1` is empty when
    n=1), so selection = Pearson correlation at 12 circular shifts, minor wins
    ties. Feeding Essentia's own mean HPCP through this reproduces its oracle
    keys 121/121 = 100%, so the whole burden is reproducing the HPCP.
  * SpectralWhitening is essential (no-whiten HPCP -> only ~55%) and is
    invariant to a constant scaling of the magnitude spectrum (all its dB
    comparisons are relative), so window/spectrum normalization constants are
    irrelevant -- only the window *shape* matters.
"""

import numpy as np

from .decode import _linear_resample, decode_mono

SR = 44100
FRAME, HOP = 4096, 4096  # KeyExtractor: non-overlapping frames, startFromZero
MIN_FREQ, MAX_FREQ = 25.0, 3500.0  # SpectralPeaks / HPCP / whitening band
REF_FREQ = 440.0
MAX_PEAKS = 60
MAG_THRESH = 1e-4

# Essentia Key 'bgate' major/minor profiles (bin 0 = tonic), verbatim from
# src/algorithms/tonal/key.cpp profileTypesWithOther[0..1].
BGATE_MAJOR = np.array([1.00, 0.00, 0.42, 0.00, 0.53, 0.37, 0.00, 0.77, 0.00, 0.38, 0.21, 0.30])
BGATE_MINOR = np.array([1.00, 0.00, 0.36, 0.39, 0.00, 0.38, 0.00, 0.74, 0.27, 0.00, 0.42, 0.23])
# key.cpp keyNames: HPCP bin 0 = A, flats.
KEY_NAMES = ["A", "Bb", "B", "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab"]

# Essentia Windowing(hann): symmetric hann, then normalized=true scales the window
# by 2/sum(|w|). This scale matters: SpectralPeaks' magnitudeThreshold (1e-4) and
# SpectralWhitening's high-freq passthrough are ABSOLUTE, so the spectrum must match
# Essentia's magnitude scale bit-for-bit (else silent frames yield spurious peaks).
_HANN = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FRAME) / (FRAME - 1))  # symmetric hann
_HANN = (_HANN * (2.0 / np.abs(_HANN).sum())).astype(np.float32)


# --------------------------------------------------------------------------- #
# SpectralPeaks == PeakDetection (standard/peakdetection.cpp), interpolate=true
# --------------------------------------------------------------------------- #
def _interpolate(left, mid, right, cur_bin):
    denom = left - 2.0 * mid + right
    delta = 0.5 * (left - right) / denom if denom != 0.0 else 0.0
    return mid - 0.25 * (left - right) * delta, cur_bin + delta


def _spectral_peaks_fast(spectrum):
    """Vectorized equivalent of `_spectral_peaks` for the common case. Essentia's
    PeakDetection climbs (strict `<`) then descends (strict `<` after the plateau),
    so an ordinary peak is a *strict* local maximum a[j-1] < a[j] > a[j+1]. Plateaus
    (exact float equality of adjacent bins) and the size-2/upper boundaries do not
    occur in real magnitude spectra; only the low-edge boundary is kept. Verified
    bit-identical to `_spectral_peaks` on the Essentia stage dumps."""
    a = spectrum
    size = len(a)
    scale = (SR / 2.0) / (size - 1.0)
    i0 = max(0, int(np.ceil(MIN_FREQ / scale)))

    # Essentia's loop starts AT i0 and climbs, so it only ever reports peaks at
    # bins > i0; bin i0 is reported solely by the low-edge boundary check below.
    j = np.arange(i0 + 1, size - 1)
    mask = (a[j] > a[j - 1]) & (a[j] > a[j + 1]) & (a[j] > MAG_THRESH)
    jj = j[mask]
    left, mid, right = a[jj - 1], a[jj], a[jj + 1]
    denom = left - 2.0 * mid + right
    delta = np.where(denom != 0.0, 0.5 * (left - right) / denom, 0.0)
    pos = (jj + delta) * scale
    val = mid - 0.25 * (left - right) * delta
    keep = pos <= MAX_FREQ
    pos, val = pos[keep], val[keep]

    out = list(zip(pos.tolist(), val.tolist()))
    # low-edge boundary peak (falling edge at the first considered bin)
    if i0 + 1 < size and a[i0] > a[i0 + 1] and a[i0] > MAG_THRESH:
        out.insert(0, (i0 * scale, float(a[i0])))

    if not out:
        return np.empty(0), np.empty(0)
    out.sort(key=lambda p: (-p[1], p[0]))
    out = out[:MAX_PEAKS]
    return np.array([p[0] for p in out]), np.array([p[1] for p in out])


def _spectral_peaks(spectrum):
    """Port of PeakDetection::compute with range=SR/2, minPos 25, maxPos 3500,
    threshold 1e-4, interpolate=true, orderBy amplitude, maxPeaks 60."""
    size = len(spectrum)
    scale = (SR / 2.0) / (size - 1.0)
    a = spectrum
    peaks = []  # (position_hz, magnitude)

    i = max(0, int(np.ceil(MIN_FREQ / scale)))
    # boundary check at the low edge
    if i + 1 < size and a[i] > a[i + 1] and a[i] > MAG_THRESH:
        peaks.append((i * scale, a[i]))

    while True:
        while i + 1 < size - 1 and a[i] >= a[i + 1]:
            i += 1
        while i + 1 < size - 1 and a[i] < a[i + 1]:
            i += 1
        j = i
        while j + 1 < size - 1 and a[j] == a[j + 1]:
            j += 1

        if j + 1 < size - 1 and a[j + 1] < a[j] and a[j] > MAG_THRESH:
            if j != i:  # plateau peak between i and j
                result_bin = (i + j) * 0.5
                result_val = a[i]
            else:  # parabolic interpolation at j-1, j, j+1
                result_val, result_bin = _interpolate(a[j - 1], a[j], a[j + 1], j)
            result_pos = result_bin * scale
            if result_pos > MAX_FREQ:
                break
            peaks.append((result_pos, result_val))

        i = j
        if i + 1 >= size - 1:
            if i == size - 2 and a[i - 1] < a[i] and a[i + 1] < a[i] and a[i] > MAG_THRESH:
                result_val, result_bin = _interpolate(a[i - 1], a[i], a[i + 1], i)
                peaks.append((result_bin * scale, result_val))
            break

    # upper boundary (never fires for maxPos << nyquist, kept for fidelity)
    pos = MAX_FREQ / scale
    if size - 2 < pos <= size - 1 and a[size - 1] > a[size - 2] and a[size - 1] > MAG_THRESH:
        peaks.append(((size - 1) * scale, a[size - 1]))

    # minPeakDistance == 0 -> sort by amplitude desc, ties by smaller position
    peaks.sort(key=lambda p: (-p[1], p[0]))
    peaks = peaks[:MAX_PEAKS]
    if not peaks:
        return np.empty(0), np.empty(0)
    freqs = np.array([p[0] for p in peaks])
    mags = np.array([p[1] for p in peaks])
    return freqs, mags


# --------------------------------------------------------------------------- #
# SpectralWhitening (spectral/spectralwhitening.cpp), maxFrequency 3500
# --------------------------------------------------------------------------- #
_BPF_RES = 100.0
_SPEC_RANGE = SR / 2.0  # 22050


def _lin2db(x):  # essentiamath.h: 10*log10(x), floor -100 below 1e-10
    return np.where(x < 1e-10, -100.0, 10.0 * np.log10(np.maximum(x, 1e-10)))


def _db2lin(x):  # essentiamath.h: 10^(x/10)
    return np.power(10.0, x / 10.0)


def _spectral_whitening(spectrum, freqs, mags):
    n = len(freqs)
    if n == 0:
        return mags
    spec_size = len(spectrum)
    mags_db = 2.0 * _lin2db(mags)

    # noise envelope over the spectrum (weighted power average in sliding bands)
    xs, ys = [], []
    freq = 0.0
    while freq <= MAX_FREQ and freq <= _SPEC_RANGE:
        bf = freq - max(50.0, freq * 0.34)
        ef = freq + max(50.0, freq * 0.58)
        b = int(bf / _SPEC_RANGE * (spec_size - 1.0) + 0.5)  # C++ int(): truncates toward 0
        e = int(ef / _SPEC_RANGE * (spec_size - 1.0) + 0.5)
        b = min(max(b, 0), spec_size - 1)
        e = min(max(e, b + 1), spec_size)
        c = b / 2.0 + e / 2.0
        halfwin = e - c
        idx = np.arange(b, e)
        w = 1.0 - np.abs(idx - c) / halfwin
        w *= w
        w *= w
        se = spectrum[b:e] * spectrum[b:e]
        w = w * se
        nn = w.sum()
        wavg = float((se * w).sum() / nn) if nn != 0.0 else 0.0
        xs.append(freq)
        ys.append(wavg)
        freq += _BPF_RES
    ys[-1] = ys[-2]
    ys = 2.0 * _lin2db(np.sqrt(np.asarray(ys)))
    xs = np.asarray(xs)

    white = np.empty(n)
    for k in range(n):
        f = freqs[k]
        amp = mags_db[k]
        # spectralwhitening.cpp passes through peaks above (_maxFreq - incr), but
        # the installed essentia (2.1-beta6) whitens everything up to _maxFreq
        # itself -- verified against per-peak dumps (peaks at 3403/3423 Hz are
        # whitened, not copied). SpectralPeaks caps peaks at MAX_FREQ, so this
        # branch never fires for real input; kept for peaks that reach the edge.
        if f > MAX_FREQ:
            white[k] = amp
            continue
        amp_env = np.interp(f, xs, ys)
        if amp > amp_env:
            w = 0.0
        elif amp > amp_env - 30.0:
            w = amp - amp_env
        else:
            w = -200.0
        white[k] = w - 20.0 * f / 4000.0
    return _db2lin(white / 2.0)


# --------------------------------------------------------------------------- #
# HPCP (spectral/hpcp.cpp), KeyExtractor config
# --------------------------------------------------------------------------- #
def _harmonic_table(n_harmonics=4, precision=1e-5):
    """Port of HPCP::initHarmonicContributionTable -> [(semitone, strength)]."""
    peaks = []
    for i in range(n_harmonics + 1):
        semitone = 12.0 * np.log2(i + 1.0)
        octweight = max(1.0, (semitone / 12.0) * 0.5)
        while semitone >= 12.0 - precision:
            semitone -= 12.0
        hit = next((p for p in peaks if p[0] - precision < semitone < p[0] + precision), None)
        if hit is None:
            peaks.append([semitone, 1.0 / octweight])
        else:
            hit[1] += 1.0 / octweight
    return peaks


_HARMONICS = _harmonic_table(4)  # [(0.0, 3.0), (7.02, 1.0), (3.86, 0.861)]


def _hpcp(freqs, mags):
    """Port of HPCP::compute for KeyExtractor config: bandPreset false,
    weightType cosine, windowSize 1.0, size 12, normalized none, nonLinear
    false, harmonics 4, referenceFrequency 440."""
    hpcp = np.zeros(12)
    for k in range(len(freqs)):
        freq = freqs[k]
        if freq < MIN_FREQ or freq > MAX_FREQ:
            continue
        mag = mags[k]
        mag2 = mag * mag
        for semitone, strength in _HARMONICS:
            f = freq * 2.0 ** (-semitone / 12.0)
            if f <= 0.0:
                continue
            hw2 = strength * strength
            pcp_bin = np.log2(f / REF_FREQ) * 12.0  # resolution*size = 12
            left = int(np.ceil(pcp_bin - 0.5))  # windowSize/2 * resolution = 0.5
            right = int(np.floor(pcp_bin + 0.5))
            for b in range(left, right + 1):
                weight = np.cos(np.pi * abs(pcp_bin - b))  # cosine, resolution=windowSize=1
                hpcp[b % 12] += weight * mag2 * hw2
    return hpcp


# --------------------------------------------------------------------------- #
# Key selection (tonal/key.cpp), profileType bgate, usePolyphony false
# --------------------------------------------------------------------------- #
def _key_from_pcp(pcp):
    """Port of Key::compute correlation loop for raw bgate profiles (size 12)."""
    mean_pcp = pcp.mean()
    std_pcp = np.sqrt(((pcp - mean_pcp) ** 2).sum())

    def best_corr(profile):
        mean_p = profile.mean()
        std_p = np.sqrt(((profile - mean_p) ** 2).sum())
        best_r, best_shift = -1.0, 0
        for shift in range(12):
            if std_pcp == 0.0 or std_p == 0.0:
                r = 0.0
            else:
                idx = (np.arange(12) - shift) % 12
                r = float(((pcp - mean_pcp) * (profile[idx] - mean_p)).sum() / (std_pcp * std_p))
            if r > best_r:  # strict '>' -> first (lowest) shift wins ties, matches C++
                best_r, best_shift = r, shift
        return best_r, best_shift

    max_major, key_major = best_corr(BGATE_MAJOR)
    max_minor, key_minor = best_corr(BGATE_MINOR)

    if max_major > max_minor:  # minor wins ties (C++: maxMinor >= maxMajor)
        return KEY_NAMES[key_major], "major", max_major
    return KEY_NAMES[key_minor], "minor", max_minor


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _frames(audio):
    """Essentia FrameCutter(frameSize 4096, hopSize 4096, startFromZero):
    non-overlapping, last partial frame zero-padded."""
    n = len(audio)
    for start in range(0, n, HOP):
        frame = audio[start : start + FRAME]
        if len(frame) < FRAME:
            frame = np.concatenate([frame, np.zeros(FRAME - len(frame), np.float32)])
        yield frame


def mean_hpcp(audio):
    """Full native pipeline up to the mean HPCP (12,). audio must be mono @ SR."""
    acc = np.zeros(12)
    count = 0
    for frame in _frames(audio):
        spectrum = np.abs(np.fft.rfft(frame * _HANN))
        freqs, mags = _spectral_peaks_fast(spectrum)
        if len(freqs):
            mags = _spectral_whitening(spectrum, freqs, mags)
        acc += _hpcp(freqs, mags)
        count += 1
    return acc / max(count, 1)


def estimate(audio, sr):
    """Estimate musical key. Returns (key, scale, strength).

    scale is "major"/"minor"; strength is the winning Pearson correlation.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if sr != SR:
        audio = _linear_resample(audio, sr, SR)
    pcp = mean_hpcp(audio)
    return _key_from_pcp(pcp)


def estimate_file(path):
    """Convenience: decode `path` to mono @ 44100 and estimate its key."""
    return estimate(decode_mono(path, SR), SR)

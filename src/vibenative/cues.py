"""DJ prep: an energy level (1-10) with its curve over time, and cue points
(intro / drops / breakdowns / outro / end) snapped to a beat grid.

Everything here is plain NumPy on the 44.1 kHz mono signal the analysis already
decodes -- no model, no extra decode. Contract::

    analyze(audio, sr, bpm) -> {
        "energy":       int 1..10,           # the track's level, judged by its peaks
        "energy_curve": [float 0..1, ...],   # one value per ENERGY_HOP seconds
        "energy_hop":   1.0,
        "grid":         {"bpm", "offset", "confidence"} or None,   # beat grid
        "cues":         [{"t", "type", "label", "bar", "energy"}, ...]
    }

How the energy is judged
------------------------
Per second of audio, three signals are read from a short-time spectrum:

  loudness    RMS in dBFS. Mastered club music sits around -8..-12 dBFS in a
              drop; ambient and downtempo 10-20 dB under that. Mapped so -30 dBFS
              is 0 and -8 dBFS is 1 -- comparable ACROSS tracks, not relative.
  flux        positive spectral flux (the onset envelope): how much new spectral
              energy arrives per frame. Dense percussion and busy sound design
              score high; a sustained pad scores near zero.
  brightness  the share of magnitude above 2 kHz: hats, noise, distortion.

They mix ``ENERGY_WEIGHTS`` into a 0..1 value per second (the curve). The
track-level number is the mean of its loudest quarter -- a DJ rates a track by
its drop, not its intro -- nudged by tempo (octave-normalised so a 174 and an 87
BPM read of the same DnB tune agree), then placed on the 1..10 scale. The
calibration constants were set on a genre spread of real tracks so that ambient
lands 1-3, house/techno 5-7, and dubstep / hard DnB 8-10.

How the cues are found
----------------------
The onset envelope is comb-filtered at the analysed BPM to find the beat
phase (which of the ~20 possible offsets lines beats up with onsets best). Bars
are 4 beats; the bar phase is chosen so the strongest drop lands on a bar line,
because in electronic music a drop *is* a phrase boundary -- that anchors the
grid to the music's own structure rather than to a guessed downbeat.

Per bar, loudness and bass (< 150 Hz) are read. A drop is a bar where the
4 bars after are much louder / bassier than the 4 before; a breakdown is the
reverse. The largest such steps (spaced at least 8 bars apart) become cues,
plus the first audible beat (intro), the last step down that never recovers
(outro), and the last audible beat (end). At most ``MAX_CUES`` -- Rekordbox
gives eight -- so a track never drowns in flags.

Without a usable BPM the same detection runs on a fixed 2-second "bar" and the
cues are not snapped (``grid`` is None).
"""

import numpy as np

SR = 11025  # analysis rate: 4x decimation of the 44.1 kHz decode (same as TempoCNN)
FRAME, HOP = 1024, 256  # 93 ms frames every 23 ms -> onset envelope at ~43 fps
FRAME_RATE = SR / HOP
CHUNK = 2048  # frames per STFT batch; bounds memory on long tracks
ENERGY_HOP = 1.0  # seconds per energy-curve point
EPS = 1e-9

# --- energy calibration (see module docstring) ---
# Set on a genre spread of real, modern masters: club music sits between -13 and
# -4 dBFS (90th-percentile second), so the loudness ramp is deliberately narrow.
LOUD_DB_FLOOR, LOUD_DB_FULL = -18.0, -4.0  # dBFS -> 0 / 1
BRIGHT_LO, BRIGHT_FULL = 0.10, 0.45  # share of magnitude above 2 kHz -> 0 / 1
FLUX_LO, FLUX_FULL = 0.8, 2.6  # mean positive log-spectral flux (dB/band/frame) -> 0 / 1
ENERGY_WEIGHTS = {"loud": 0.55, "bright": 0.25, "flux": 0.10}  # the curve (sums to 0.9)
TEMPO_WEIGHT = 0.10  # the rest: a fast (octave-normalised) tempo lifts the level
TEMPO_NEUTRAL = 0.35  # tempo term used when the track has no BPM (~128 BPM's)
PEAK_SHARE = 0.25  # the track's level = mean energy of its loudest quarter
LEVEL_LO, LEVEL_HI = 0.20, 0.85  # peak energy mapped onto levels 1 .. 10

# --- cue detection ---
BEATS_PER_BAR = 4
CONTRAST_BARS = 4  # bars compared on each side of a candidate boundary
MIN_CUE_GAP_BARS = 8  # two structural cues can't be closer than this
DROP_DB = 3.5  # loudness+bass step (dB) that counts as a drop / breakdown
PEAK_ZONE_DB = 4.0  # a step up landing within this of the loudest bars is a drop, else a build
EDGE_START_BARS, EDGE_END_BARS = 6, 6  # no structural cue this close to the intro / end
SILENCE_DB = 40.0  # below (peak - this) is treated as silence for intro/end
BASS_FLOOR_DB = 30.0  # per-bar bass is floored this far under the bassiest bar
MAX_CUES = 8
GRID_MIN_CONFIDENCE = 1.5  # comb-filter best / mean below this = no usable grid
BPM_REFINE = 1.5  # search this far either side of the analysed BPM (TempoCNN is 1-BPM coarse)
BPM_STEP = 0.05

_HANN = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FRAME) / FRAME)).astype(np.float32)
_FREQS = np.fft.rfftfreq(FRAME, 1.0 / SR)
_BASS = _FREQS < 150.0
_HIGH = _FREQS >= 2000.0
# a coarse log-spaced band grouping of the spectrum for the flux read (40 bands,
# 20 Hz .. 5 kHz, like TempoCNN's mel input) -- bands, not bins, so one loud
# partial wobbling between two bins doesn't register as an onset.
_N_BANDS = 40
_BAND_EDGES = np.geomspace(20.0, 5000.0, _N_BANDS + 1)
_BAND_OF = np.searchsorted(_BAND_EDGES, _FREQS, side="right") - 1
_BANDS = np.zeros((_FREQS.size, _N_BANDS), dtype=np.float32)  # bin -> band, 0/1
for _k, _b in enumerate(_BAND_OF):
    if 0 <= _b < _N_BANDS:
        _BANDS[_k, _b] = 1.0


def _resample(x, sr):
    """Linear-interpolation resample to SR (the tempo path's own approach)."""
    x = np.asarray(x, dtype=np.float32).ravel()
    if sr == SR:
        return x
    n = int(round(len(x) * SR / sr))
    pos = np.arange(n) * (sr / SR)
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(x) - 1)
    frac = (pos - np.floor(pos)).astype(np.float32)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    return (1 - frac) * x[i0] + frac * x[i1]


def frame_features(x):
    """Per-frame ``(rms, bass_rms, flux, bright)`` from the SR-rate signal.

    rms / bass_rms are linear amplitudes; flux is the mean positive change in
    log band magnitude (dB per band per frame, floored at zero); bright is the
    share of spectral magnitude above 2 kHz. All float32, one row per frame."""
    x = np.asarray(x, dtype=np.float32)
    n = (len(x) - FRAME) // HOP + 1
    if n <= 0:
        return np.zeros((0, 4), dtype=np.float32)
    out = np.zeros((n, 4), dtype=np.float32)
    prev = None
    for start in range(0, n, CHUNK):
        stop = min(n, start + CHUNK)
        idx = HOP * np.arange(start, stop)[:, None] + np.arange(FRAME)[None, :]
        fr = x[idx]
        out[start:stop, 0] = np.sqrt(np.mean(fr * fr, axis=1))
        mag = np.abs(np.fft.rfft(fr * _HANN, axis=1)).astype(np.float32)
        total = mag.sum(axis=1) + EPS
        out[start:stop, 1] = np.sqrt((mag[:, _BASS] ** 2).sum(axis=1)) / (FRAME / 4)
        out[start:stop, 3] = mag[:, _HIGH].sum(axis=1) / total
        # log band magnitudes -> positive flux against the previous frame
        logb = 20.0 * np.log10(mag @ _BANDS + 1e-4)
        if prev is None:
            prev = logb[:1]
        d = np.diff(np.concatenate([prev, logb], axis=0), axis=0)
        out[start:stop, 2] = np.maximum(d, 0.0).mean(axis=1)
        prev = logb[-1:]
    return out


def _db(a):
    return 20.0 * np.log10(np.maximum(np.asarray(a, dtype=np.float64), EPS))


def _pool(values, index, n, how="mean"):
    """Pool per-frame ``values`` into ``n`` groups by integer ``index``."""
    index = np.asarray(index)
    keep = (index >= 0) & (index < n)
    counts = np.bincount(index[keep], minlength=n).astype(np.float64)
    if how == "rms":
        s = np.bincount(index[keep], weights=values[keep] ** 2, minlength=n)
        return np.sqrt(s / np.maximum(counts, 1))
    s = np.bincount(index[keep], weights=values[keep], minlength=n)
    return s / np.maximum(counts, 1)


def _clip01(v):
    return np.clip(v, 0.0, 1.0)


def energy_curve(feat, duration):
    """Per-``ENERGY_HOP``-second energy in 0..1 from the frame features (the
    tempo term is track-level, so the curve alone tops out at 0.9)."""
    n = max(1, int(np.ceil(duration / ENERGY_HOP)))
    if feat.shape[0] == 0:
        return np.zeros(n)
    t = (np.arange(feat.shape[0]) * HOP + FRAME / 2) / SR
    sec = np.floor(t / ENERGY_HOP).astype(int)
    loud = _clip01(
        (_db(_pool(feat[:, 0], sec, n, "rms")) - LOUD_DB_FLOOR) / (LOUD_DB_FULL - LOUD_DB_FLOOR)
    )
    bright = _clip01((_pool(feat[:, 3], sec, n) - BRIGHT_LO) / (BRIGHT_FULL - BRIGHT_LO))
    flux = _clip01((_pool(feat[:, 2], sec, n) - FLUX_LO) / (FLUX_FULL - FLUX_LO))
    w = ENERGY_WEIGHTS
    return w["loud"] * loud + w["bright"] * bright + w["flux"] * flux


def _octave_bpm(bpm):
    """Fold a tempo into [90, 180) so half/double-time reads agree."""
    b = float(bpm)
    while b and b < 90:
        b *= 2
    while b >= 180:
        b /= 2
    return b


def _tempo_term(bpm):
    if not bpm:
        return TEMPO_NEUTRAL
    return float(_clip01((_octave_bpm(bpm) - 100.0) / 80.0))


def level_of(value, bpm=None):
    """Map one 0..1 curve value (plus the track's tempo) onto the 1..10 scale."""
    v = float(value) + TEMPO_WEIGHT * _tempo_term(bpm)
    return int(np.clip(round(1 + 9 * (v - LEVEL_LO) / (LEVEL_HI - LEVEL_LO)), 1, 10))


def energy_level(curve, bpm=None):
    """The 1..10 level: mean of the loudest quarter of the curve, tempo-nudged."""
    c = np.sort(np.asarray(curve, dtype=np.float64))
    if c.size == 0:
        return 1
    k = max(1, int(np.ceil(c.size * PEAK_SHARE)))
    return level_of(float(c[-k:].mean()), bpm)


def whiten_onsets(flux, window_s=0.5):
    """Sharpen the flux envelope into onsets: subtract a moving local mean and
    keep the positive part, so sustained content stops counting as beats."""
    f = np.asarray(flux, dtype=np.float64)
    if f.size == 0:
        return f
    w = max(1, int(round(window_s * FRAME_RATE)))
    local = np.convolve(f, np.ones(w) / w, mode="same")
    return np.maximum(f - local, 0.0)


def beat_grid(onset, bpm):
    """Fit a beat grid to the onset envelope around ``bpm``. Returns
    ``(bpm, offset_frames, confidence)``: the refined tempo, the fractional
    frame of the first beat, and how much better the best (tempo, phase) scores
    than the average phase (1.0 = no beat structure at all).

    A comb of beats at every candidate tempo (+/- BPM_REFINE in BPM_STEP steps,
    because a 0.4 BPM error drifts two beats across a 5-minute track) and every
    phase on a quarter-frame lattice; the comb that lands on the most onset
    energy wins."""
    onset = np.asarray(onset, dtype=np.float64)
    idx = np.arange(onset.size)
    best = (float(bpm), 0.0, 0.0)
    if onset.size < 4 * 60.0 * FRAME_RATE / float(bpm):
        return best
    for b in np.arange(float(bpm) - BPM_REFINE, float(bpm) + BPM_REFINE + 1e-9, BPM_STEP):
        period = 60.0 * FRAME_RATE / b
        phases = np.arange(0.0, period, 0.25)
        n_beats = int((onset.size - 1 - period) // period)
        pos = phases[:, None] + np.arange(n_beats)[None, :] * period
        scores = np.interp(pos.ravel(), idx, onset).reshape(pos.shape).mean(axis=1)
        i = int(scores.argmax())
        conf = float(scores[i] / (scores.mean() or 1.0))
        if conf > best[2]:
            best = (round(float(b), 2), float(phases[i]), conf)
    return best


def _contrast(series, w):
    """Step contrast at each bar: mean of the next ``w`` minus mean of the previous
    ``w`` (NaN where a full window doesn't fit)."""
    n = series.size
    out = np.full(n, np.nan)
    if n < 2 * w:
        return out
    # NaN bars (silence) are left out of each window's mean; a window that is
    # mostly silence gives no contrast, so leading / trailing silence never reads
    # as a structural step.
    ok = np.isfinite(series)
    vals = np.where(ok, series, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(vals)])
    cn = np.concatenate([[0], np.cumsum(ok)])
    for i in range(w, n - w + 1):
        n_after, n_before = cn[i + w] - cn[i], cn[i] - cn[i - w]
        if n_after * 2 >= w and n_before * 2 >= w:
            out[i] = (cs[i + w] - cs[i]) / n_after - (cs[i] - cs[i - w]) / n_before
    return out


def _pick_peaks(contrast, sign, min_gap):
    """Indices of the strongest local extrema of ``sign * contrast`` above
    ``DROP_DB``, greedily thinned so none are closer than ``min_gap``."""
    c = sign * np.asarray(contrast, dtype=np.float64)
    ok = np.isfinite(c)
    # a peak needs both neighbours defined: the first / last defined bar is an
    # edge of the window, not a maximum
    cand = [
        i
        for i in range(1, c.size - 1)
        if ok[i - 1] and ok[i] and ok[i + 1] and c[i] >= DROP_DB and c[i - 1] <= c[i] > c[i + 1]
    ]
    cand.sort(key=lambda i: -c[i])
    picked = []
    for i in cand:
        if all(abs(i - j) >= min_gap for j in picked):
            picked.append(i)
    return picked


def _bar_steps(feat, t_frame, floor_db, offset, bar_len, duration):
    """Per-bar loudness and the loudness+bass step contrast on a grid that
    starts at ``offset``. Bars below ``floor_db`` are silence (NaN)."""
    n_bars = max(1, int(np.ceil((duration - offset) / bar_len)))
    bar_of = np.floor((t_frame - offset) / bar_len).astype(int)
    loud = _db(_pool(feat[:, 0], bar_of, n_bars, "rms"))
    bass = _db(_pool(feat[:, 1], bar_of, n_bars, "rms"))
    silent = loud <= floor_db
    loud[silent] = np.nan
    bass[silent] = np.nan
    # A breakdown with no sub at all reads as -80 dB of bass; on a dB scale that
    # would outweigh every loudness change around it. Floor it: "no bass" is
    # BASS_FLOOR_DB under the track's bassiest bar, not minus infinity.
    if np.isfinite(bass).any():
        bass = np.maximum(bass, np.nanmax(bass) - BASS_FLOOR_DB)
    step = 0.5 * _contrast(loud, CONTRAST_BARS) + 0.5 * _contrast(bass, CONTRAST_BARS)
    return loud, step


def detect_cues(feat, duration, bpm=None):
    """Cue points + beat grid from the frame features. See the module docstring."""
    n_frames = feat.shape[0]
    if n_frames == 0:
        return None, []
    t_frame = (np.arange(n_frames) * HOP + FRAME / 2) / SR
    loud_frame = _db(feat[:, 0])
    floor_db = float(loud_frame.max()) - SILENCE_DB
    audible = loud_frame > floor_db

    # --- beat grid ---
    grid = None
    beat_len = 2.0 / BEATS_PER_BAR  # fallback "beat" when there's no tempo: 0.5 s
    offset = 0.0
    if bpm:
        gbpm, ph, conf = beat_grid(whiten_onsets(feat[:, 2]), bpm)
        if conf >= GRID_MIN_CONFIDENCE:
            beat_len = 60.0 / gbpm
            offset = (ph * HOP + FRAME / 2) / SR
            grid = {"bpm": gbpm, "offset": round(offset, 4), "confidence": round(conf, 3)}
    bar_len = beat_len * BEATS_PER_BAR

    loud, step = _bar_steps(feat, t_frame, floor_db, offset, bar_len, duration)
    ups = _pick_peaks(step, +1, MIN_CUE_GAP_BARS)

    # Anchor the BAR phase to the strongest step up: shift the grid so the beat
    # where the bass lands is beat 1 of a bar. Beat positions are unchanged;
    # only which beat counts as the downbeat moves (0..3 beats).
    if grid is not None and ups:
        main = max(ups, key=lambda i: step[i])
        t0 = offset + main * bar_len
        bass_frame = _db(feat[:, 1])
        best_beat, best_jump = 0, -np.inf
        for b in range(BEATS_PER_BAR):
            tb = t0 + b * beat_len
            before = bass_frame[(t_frame >= tb - beat_len) & (t_frame < tb)]
            after = bass_frame[(t_frame >= tb) & (t_frame < tb + beat_len)]
            if before.size and after.size:
                jump = float(after.mean() - before.mean())
                if jump > best_jump:
                    best_jump, best_beat = jump, b
        if best_beat:
            offset += best_beat * beat_len
            loud, step = _bar_steps(feat, t_frame, floor_db, offset, bar_len, duration)
            ups = _pick_peaks(step, +1, MIN_CUE_GAP_BARS)
        grid["offset"] = round(offset, 4)
    downs = _pick_peaks(step, -1, MIN_CUE_GAP_BARS)

    def snap(t, unit):
        """Nearest grid line ``unit`` seconds apart (the time itself with no
        grid), kept inside the track: past either end, the nearest line within."""
        if grid is None:
            return max(0.0, min(duration, t))
        k = round((t - offset) / unit)
        k = max(k, int(np.ceil(-offset / unit)))
        k = min(k, int(np.floor((duration - offset) / unit)))
        return offset + k * unit

    cues = []
    aud_idx = np.flatnonzero(audible)
    if not aud_idx.size:
        return grid, cues
    # the first audible beat is bar 1 (snapped to a downbeat: tracks start on one)
    t_start = snap(float(t_frame[aud_idx[0]]), bar_len)
    t_end = snap(float(t_frame[aud_idx[-1]]), beat_len)
    cues.append({"t": t_start, "type": "start"})
    if t_end - t_start > 2 * bar_len:
        cues.append({"t": t_end, "type": "end"})

    # A step up is a drop when what follows sits in the track's loudest zone,
    # otherwise a build (energy rising, not there yet). A step down is a
    # breakdown -- or the outro when nothing rises again after it.
    finite = loud[np.isfinite(loud)]
    peak_zone = (float(np.percentile(finite, 90)) - PEAK_ZONE_DB) if finite.size else -np.inf
    structural = []
    for i in ups:
        after = loud[i : i + CONTRAST_BARS]
        after = after[np.isfinite(after)]
        loud_after = float(after.mean()) if after.size else -np.inf
        kind = "drop" if loud_after >= peak_zone else "build"
        structural.append({"i": i, "type": kind, "strength": float(step[i])})
    last_up = max(ups) if ups else -1
    downs.sort()
    for n, i in enumerate(downs):
        is_last = n == len(downs) - 1
        kind = "outro" if is_last and i > last_up and ups else "break"
        structural.append({"i": i, "type": kind, "strength": float(-step[i])})
    # Steps hugging the intro or the end are the opening hit and the fade, not
    # structure (and the first contrast window is only half-defined there).
    keep = []
    for s in structural:
        t = offset + s["i"] * bar_len
        if t - t_start >= EDGE_START_BARS * bar_len and t_end - t >= EDGE_END_BARS * bar_len:
            keep.append(s)
    # cap: the intro/end pair stays; the rest by strength
    keep.sort(key=lambda s: -s["strength"])
    for s in keep[: max(0, MAX_CUES - len(cues))]:
        cues.append({"t": snap(offset + s["i"] * bar_len, beat_len), "type": s["type"]})
    cues.sort(key=lambda c: c["t"])

    labels = {"start": "Intro", "end": "End", "build": "Build", "break": "Break", "outro": "Outro"}
    n_drop = 0
    for c in cues:
        if c["type"] == "drop":
            n_drop += 1
            c["label"] = f"Drop {n_drop}"
        else:
            c["label"] = labels[c["type"]]
        c["bar"] = int(np.floor((c["t"] - t_start) / bar_len + 1e-6)) + 1 if grid else None
        c["t"] = round(float(c["t"]), 3)
    return grid, cues


def analyze(audio, sr, bpm=None):
    """Energy level + curve, beat grid and cue points for one track (see module)."""
    x = _resample(audio, sr)
    duration = len(x) / SR
    feat = frame_features(x)
    curve = energy_curve(feat, duration)
    level = energy_level(curve, bpm)
    grid, cues = detect_cues(feat, duration, bpm)
    # each cue carries the level of the 8 seconds that follow it
    for c in cues:
        a = int(c["t"] / ENERGY_HOP)
        seg = curve[a : a + 8]
        c["energy"] = level_of(seg.mean(), bpm) if seg.size else level
    return {
        "energy": level,
        "energy_curve": [round(float(v), 3) for v in curve],
        "energy_hop": ENERGY_HOP,
        "grid": grid,
        "cues": cues,
    }

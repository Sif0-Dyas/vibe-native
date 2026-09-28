"""The chunked 16 kHz mel frontend and tempo frontend equal their whole-track versions.

Chunking changed only how much is alive at once, never the arithmetic. The
pre-chunking implementations are kept here as the reference; outputs must match
bit for bit. Signals span several blocks, and one is shorter than a frame.
"""

import numpy as np
import pytest

from vibenative import frontend_mel as F
from vibenative import tempo as T


def _whole_track_mel16(audio16):
    x = np.asarray(audio16, dtype=np.float64).ravel()
    n_frames = 1 + len(x) // F.HOP
    pad = F.FRAME // 2
    xp = np.zeros(pad + (n_frames - 1) * F.HOP + F.FRAME, dtype=np.float64)
    xp[pad : pad + len(x)] = x
    frames = xp[F.HOP * np.arange(n_frames)[:, None] + np.arange(F.FRAME)[None, :]]
    spec = np.abs(np.fft.rfft(frames * F._HANN, axis=1))
    return np.log10(1.0 + 10000.0 * ((spec * spec) @ F._MEL_FB.T)).astype(np.float32)


def _whole_track_resample(x, sr):
    x = x.astype(np.float64)
    n = int(round(len(x) * T.SR / sr))
    pos = np.arange(n) * (sr / T.SR)
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(x) - 1)
    frac = pos - np.floor(pos)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    return (1 - frac) * x[i0] + frac * x[i1]


def _whole_track_tempo_mel(audio):
    x = np.asarray(audio, dtype=np.float64)
    if len(x) < T.FRAME:
        return np.empty((0, T.N_MELS), dtype=np.float32)
    n = (len(x) - T.FRAME) // T.HOP + 1
    frames = x[T.HOP * np.arange(n)[:, None] + np.arange(T.FRAME)[None, :]]
    return (np.abs(np.fft.rfft(frames * T._HANN, axis=1)) @ T._MELFB).astype(np.float32)


def _signal(seconds, sr):
    rng = np.random.default_rng(11)
    return (0.1 * rng.standard_normal(int(sr * seconds))).astype(np.float32)


@pytest.mark.parametrize("seconds", [0.01, 45.0])  # under one frame; ~2,800 frames
def test_mel16_equals_whole_track(seconds):
    x = _signal(seconds, 16000)
    new, old = F.melspectrogram(x), _whole_track_mel16(x)
    assert new.shape == old.shape and new.dtype == np.float32
    assert np.array_equal(new, old)


@pytest.mark.parametrize("seconds", [0.02, 200.0])  # 200 s at 44.1 kHz: several blocks each
def test_tempo_frontend_equals_whole_track(seconds):
    x = _signal(seconds, 44100)
    r_new, r_old = T._resample_11025(x, 44100), _whole_track_resample(x, 44100)
    assert np.array_equal(r_new, r_old)
    m_new, m_old = T._melspectrogram(r_new), _whole_track_tempo_mel(r_old)
    assert m_new.shape == m_old.shape and np.array_equal(m_new, m_old)

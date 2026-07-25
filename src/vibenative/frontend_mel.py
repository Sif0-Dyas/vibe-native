"""Mel-spectrogram frontend matching Essentia's Discogs-EffNet input EXACTLY.

Contract (tests/test_oracle_match.py judges):
    melspectrogram(audio16) -> (n_frames, 96) float32 log-mel
    patches(mel, hop_frames) -> (n_patches, 128, 96) float32 sliding windows

================================ VERIFIED PARAMETERS ================================
Discogs-EffNet's input is produced by Essentia's `TensorflowInputMusiCNN` frontend,
driven by `TensorflowPredictEffnetDiscogs`. Values below are read from the Essentia
source + the Essentia team's own reproduction notes (citations inline), NOT the
plan's hypothesis. The embedder JSON (models/discogs-effnet-bsdynamic-1.json) agrees:
input serving_default_melspectrogram [n, 128, 96], sample_rate 16000 — no conflict.

STFT / framing  [tensorflowpredicteffnetdiscogs.{cpp,h}: FrameCutter("frameSize",512,
                 "hopSize",256); TensorflowInputMusiCNN Windowing type="hann",
                 normalized=false]
    sample_rate 16000 · frame 512 · hop 256 · window hann · no window normalization
    FrameCutter default startFromZero=false => first frame CENTERED at sample 0
    (== librosa center=True: pad frame/2=256 zeros each side; n_frames = 1+len//hop).

spectrum / mel  [TriangularBands: type="power" squares the spectrum before weighting;
                 normalize="unit_tri" divides each triangle by (f_hi-f_lo)/2 -- the
                 source comment: "similar to how normalization is implemented in
                 Librosa" (i.e. Slaney equal-area); warpingFormula="slaneyMel"]
    power spectrum |rfft|**2 (257 bins) -> 96 mel bands, fmin 0, fmax 8000,
    Slaney mel scale (htk=False), Slaney/area filter norm. == librosa.filters.mel(
    sr=16000, n_fft=512, n_mels=96, fmin=0, fmax=8000, htk=False, norm="slaney").

log compression [essentia-labs "TensorFlow models in Essentia" (2019-10-19):
                 UnaryOperator(shift=1, scale=10000) then UnaryOperator(type="log10")]
    logmel = log10(1 + 10000 * mel_power)          (log10, NOT natural log)

patch layout    [tensorflowpredicteffnetdiscogs.h defaults: patchSize=128,
                 patchHopSize=62, batchSize=64; VectorRealToTensor lastPatchMode=
                 "discard", lastBatchMode="discard"]
    128 frames x 96 bands, hop 62 (coarse; smaller hop = the app's fine mode),
    incomplete trailing patch DISCARDED.

Sources: github.com/MTG/essentia src/algorithms/machinelearning/
tensorflowpredicteffnetdiscogs.{cpp,h} and src/algorithms/spectral/
{melbands,triangularbands}.cpp; mtg.github.io/essentia-labs/news/tensorflow/
2019/10/19/tensorflow-models-in-essentia/ ; essentia issue #1471.

Residual ambiguities left for the oracle to settle (cosine > 0.999 decides):
hann symmetric-vs-periodic, exact FrameCutter edge/count, decode resampler. Do NOT
lower the threshold to hide a mismatch — a plateau is a real signal.
====================================================================================
"""

import numpy as np

SR = 16000
FRAME = 512
HOP = 256
N_MELS = 96
FMIN, FMAX = 0.0, 8000.0
PATCH = 128
PATCH_HOP_COARSE = 62


def _hann(size: int) -> np.ndarray:
    # Essentia Windowing "hann" is symmetric: 0.5 - 0.5*cos(2*pi*i/(size-1)).
    i = np.arange(size)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * i / (size - 1))).astype(np.float64)


def _slaney_mel_filterbank() -> np.ndarray:
    """(N_MELS, FRAME/2+1) filterbank == librosa.filters.mel(htk=False, norm='slaney')
    == Essentia MelBands(warpingFormula='slaneyMel', normalize='unit_tri')."""
    n_freqs = FRAME // 2 + 1
    fft_hz = np.linspace(0.0, SR / 2.0, n_freqs)

    f_sp = 200.0 / 3.0
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0

    def hz2mel(f):
        f = np.asarray(f, dtype=np.float64)
        return np.where(
            f >= min_log_hz,
            min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / logstep,
            f / f_sp,
        )

    def mel2hz(m):
        m = np.asarray(m, dtype=np.float64)
        return np.where(
            m >= min_log_mel,
            min_log_hz * np.exp(logstep * (m - min_log_mel)),
            f_sp * m,
        )

    edges = mel2hz(np.linspace(hz2mel(FMIN), hz2mel(FMAX), N_MELS + 2))
    fb = np.zeros((N_MELS, n_freqs), dtype=np.float64)
    for i in range(N_MELS):
        lo, ce, hi = edges[i], edges[i + 1], edges[i + 2]
        up = (fft_hz - lo) / (ce - lo)
        down = (hi - fft_hz) / (hi - ce)
        fb[i] = np.maximum(0.0, np.minimum(up, down)) * (2.0 / (hi - lo))  # Slaney area norm
    return fb.astype(np.float64)


_HANN = _hann(FRAME)
_MEL_FB = _slaney_mel_filterbank()  # (96, 257)


def melspectrogram(audio16: np.ndarray) -> np.ndarray:
    """16 kHz mono float32 -> (n_frames, 96) log-mel, matching Essentia's frontend."""
    x = np.asarray(audio16, dtype=np.float64).ravel()
    n_frames = 1 + len(x) // HOP  # FrameCutter startFromZero=false / librosa center=True
    pad = FRAME // 2
    need = pad + (n_frames - 1) * HOP + FRAME
    xp = np.zeros(need, dtype=np.float64)
    xp[pad : pad + len(x)] = x  # left-pad frame/2; right auto zero-padded

    starts = HOP * np.arange(n_frames)
    frames = xp[starts[:, None] + np.arange(FRAME)[None, :]]  # (n_frames, 512)
    spec = np.abs(np.fft.rfft(frames * _HANN, axis=1))  # magnitude (n_frames, 257)
    mel_power = (spec * spec) @ _MEL_FB.T  # type='power' -> square, then filterbank
    return np.log10(1.0 + 10000.0 * mel_power).astype(np.float32)


def patches(mel: np.ndarray, hop_frames: int = PATCH_HOP_COARSE) -> np.ndarray:
    """(n_frames, 96) -> (n_patches, 128, 96); incomplete trailing patch discarded."""
    n = mel.shape[0]
    if n < PATCH:
        return np.empty((0, PATCH, N_MELS), dtype=np.float32)
    starts = np.arange(0, n - PATCH + 1, hop_frames)
    return np.stack([mel[s : s + PATCH] for s in starts]).astype(np.float32)

"""BPM via TempoCNN (deeptemp-k16, ONNX). Contract (Phase 3):

    estimate(audio: np.ndarray, sr: int) -> (bpm: float, confidence: float)

Acceptance vs oracle: within 2% OR a half/double multiple for >= 95% of tracks.
The app's UI already renders the octave ambiguity ("87.0/174.0?").

Frontend = Essentia TensorflowInputTempoCNN = librosa magnitude mel-spectrogram
(sr 11025, n_fft 1024, hop 512, power=1, 40 bands, fmin 20, fmax 5000, slaney
norm, NO log; non-centered frames) — verified against Essentia's own mel to
maxdiff 0.018. deeptemp-k16-3.json: 256-class softmax, class 0 = 30 BPM, class
255 = 286 BPM. Patches of 256 frames, hop 128; per-patch argmax -> local BPM;
global BPM by majority vote (Essentia TempoCNN's default aggregationMethod).
"""

import numpy as np
import onnxruntime as ort

from .paths import models_dir

MODELS = models_dir()  # exe-adjacent models/ in a packaged build, else <repo>/models
SR = 11025
FRAME, HOP, N_MELS = 1024, 512, 40
FMIN, FMAX = 20.0, 5000.0
PATCH, PATCH_HOP = 256, 128
# Cap patches per Session.run (see onnx_engine.EMB_BATCH): a long track's full patch
# stack fed to the DirectML EP at once can balloon memory and OOM-crash a batch scan.
PATCH_BATCH = 64
PROVIDER_ORDER = ["DmlExecutionProvider", "CPUExecutionProvider"]


def _mel_filterbank() -> np.ndarray:
    freqs = np.linspace(0.0, SR / 2.0, FRAME // 2 + 1)
    f_sp, min_log_hz = 200.0 / 3.0, 1000.0
    min_log_mel, step = min_log_hz / f_sp, np.log(6.4) / 27.0

    def h2m(f):
        f = np.asarray(f, float)
        return np.where(
            f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / step, f / f_sp
        )

    def m2h(m):
        m = np.asarray(m, float)
        return np.where(m >= min_log_mel, min_log_hz * np.exp(step * (m - min_log_mel)), f_sp * m)

    edges = m2h(np.linspace(h2m(FMIN), h2m(FMAX), N_MELS + 2))
    fb = np.zeros((N_MELS, len(freqs)))
    for i in range(N_MELS):
        lo, ce, hi = edges[i], edges[i + 1], edges[i + 2]
        fb[i] = np.maximum(0.0, np.minimum((freqs - lo) / (ce - lo), (hi - freqs) / (hi - ce))) * (
            2.0 / (hi - lo)
        )
    return fb.T.astype(np.float64)  # (n_freqs, 40)


_MELFB = _mel_filterbank()
_HANN = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FRAME) / FRAME)).astype(np.float64)  # periodic
_engine: dict = {}


def _session() -> ort.InferenceSession:
    if "sess" not in _engine:
        path = MODELS / "tempocnn.onnx"
        if not path.exists():
            raise FileNotFoundError("tempocnn.onnx missing — run tools/convert_models.py")
        avail = set(ort.get_available_providers())
        providers = [p for p in PROVIDER_ORDER if p in avail] or ["CPUExecutionProvider"]
        s = ort.InferenceSession(str(path), providers=providers)
        _engine.update(sess=s, inn=s.get_inputs()[0].name, outn=s.get_outputs()[0].name)
    return _engine["sess"]


def _resample_11025(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x.astype(np.float64)
    x = x.astype(np.float64)
    n = int(round(len(x) * SR / sr))
    pos = np.arange(n) * (sr / SR)
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(x) - 1)
    frac = pos - np.floor(pos)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    return (1 - frac) * x[i0] + frac * x[i1]


def _melspectrogram(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64)
    if len(x) < FRAME:
        return np.empty((0, N_MELS), dtype=np.float32)
    n = (len(x) - FRAME) // HOP + 1  # non-centered (startFromZero)
    frames = x[HOP * np.arange(n)[:, None] + np.arange(FRAME)[None, :]]
    mag = np.abs(np.fft.rfft(frames * _HANN, axis=1))  # power=1 (magnitude)
    return (mag @ _MELFB).astype(np.float32)


def estimate(audio: np.ndarray, sr: int) -> tuple[float, float]:
    """(bpm, confidence) for a track. confidence = mean per-patch peak softmax."""
    mel = _melspectrogram(_resample_11025(audio, sr))
    if mel.shape[0] < PATCH:
        return 0.0, 0.0
    sess = _session()
    starts = range(0, mel.shape[0] - PATCH + 1, PATCH_HOP)
    patches = np.stack([mel[s : s + PATCH].T for s in starts])[:, :, :, None].astype(np.float32)
    inn, outn = _engine["inn"], _engine["outn"]
    soft = np.concatenate(  # per-PATCH_BATCH runs, not one giant run — see PATCH_BATCH
        [sess.run([outn], {inn: patches[i : i + PATCH_BATCH]})[0] for i in range(0, len(patches), PATCH_BATCH)],
        axis=0,
    )  # (n_patches, 256)

    # Aggregate by AVERAGING the per-patch softmax distributions, then argmax. This
    # beats Essentia's default "majority" vote-of-argmaxes against the oracle
    # (96.7% vs 95.0% within 2%/octave) -- averaging is steadier when a track's
    # patches split across an octave. confidence = the averaged peak probability.
    dist = soft.mean(axis=0)  # (256,)
    cls = int(dist.argmax())
    return round(30.0 + cls * 256.0 / 255.0, 1), float(dist[cls])

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

import threading

import numpy as np

from . import frontend_mel
from .paths import models_dir

MODELS = models_dir()  # exe-adjacent models/ in a packaged build, else <repo>/models
SR = 11025
FRAME, HOP, N_MELS = 1024, 512, 40
FMIN, FMAX = 20.0, 5000.0
PATCH, PATCH_HOP = 256, 128
# Cap patches per Session.run (see onnx_engine.EMB_BATCH): a long track's full patch
# stack fed to the DirectML EP at once can balloon memory and OOM-crash a batch scan.
PATCH_BATCH = 64


# (n_freqs, 40): transposed, as the magnitude spectrum multiplies it on the right.
_MELFB = frontend_mel.slaney_mel_filterbank(SR, FRAME, N_MELS, FMIN, FMAX).T.astype(np.float64)
_HANN = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(FRAME) / FRAME)).astype(np.float64)  # periodic
_engine: dict = {}

# Guards BOTH building the shared session and running it.
#
# analysis.py already serialises the genre pass ("the one shared inference pass")
# but its comment says decode/BPM/key "stay parallel" -- so TempoCNN, which is
# also ONNX, was left unguarded while /batch runs three workers. Two races follow:
#
#   1. Construction. Three threads can each see "sess" not in _engine, each build
#      an InferenceSession, and the last _engine.update() wins. The losers are
#      dropped while a thread may still be inside Run() on one -- a use-after-free
#      in native code, which surfaces as an access violation, not a Python error.
#   2. Execution. Concurrent Run() on one session is documented as supported, but
#      it is the only unserialised inference left here, and batch scans have been
#      dying with 0xc0000005 inside onnxruntime_pybind11_state.pyd.
#
# The cost is small: TempoCNN is the cheap model and decode (the actual bottleneck)
# stays parallel.
_lock = threading.Lock()


def _session():  # -> onnxruntime.InferenceSession (imported lazily below, so not annotated)
    # Import onnxruntime lazily, NOT at module top: importing this module must not
    # require the Windows-only onnxruntime-directml wheel. pytest collects
    # tests/test_analysis.py (which imports `tempo`) with the stand-in engines / on CI where that
    # wheel is absent — a top-level import here ImportErrored and aborted the whole
    # suite at collection (see tests/test_import_safety.py, the guard for this).
    import onnxruntime as ort

    from . import onnx_engine  # lazy for the same reason: it imports onnxruntime at top

    if "sess" not in _engine:
        path = MODELS / "tempocnn.onnx"
        if not path.exists():
            raise FileNotFoundError("tempocnn.onnx missing — run tools/convert_models.py")
        # One provider policy for every session: CPU unless VIBE_PROVIDER=gpu.
        s = ort.InferenceSession(str(path), providers=onnx_engine.resolve_providers())
        _engine.update(sess=s, inn=s.get_inputs()[0].name, outn=s.get_outputs()[0].name)
    return _engine["sess"]


# Work in blocks, never whole-track arrays: output samples per resampling block, and
# frames per mel block. Done over a whole track, the float64 copy of the 44.1 kHz
# input, the index arrays, frame matrix and complex128 FFT peaked at ~540 MB.
RESAMPLE_BLOCK = 1 << 20
BLOCK_FRAMES = 1024


def _resample_11025(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x.astype(np.float64)
    x = np.asarray(x)
    n = int(round(len(x) * SR / sr))
    ratio = sr / SR
    out = np.empty(n, dtype=np.float64)
    for s in range(0, n, RESAMPLE_BLOCK):
        # the same positions arange(n) * ratio gives, one block at a time
        pos = np.arange(s, min(n, s + RESAMPLE_BLOCK)) * ratio
        i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(x) - 1)
        frac = pos - np.floor(pos)
        i1 = np.clip(i0 + 1, 0, len(x) - 1)
        # gathered samples widen to float64 exactly, as x.astype(float64)[i] did
        out[s : s + len(pos)] = (1 - frac) * x[i0].astype(np.float64) + frac * x[i1].astype(
            np.float64
        )
    return out


def _melspectrogram(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64)
    if len(x) < FRAME:
        return np.empty((0, N_MELS), dtype=np.float32)
    n = (len(x) - FRAME) // HOP + 1  # non-centered (startFromZero)
    frames = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::HOP][:n]  # a view
    out = np.empty((n, N_MELS), dtype=np.float32)
    for s in range(0, n, BLOCK_FRAMES):
        mag = np.abs(np.fft.rfft(frames[s : s + BLOCK_FRAMES] * _HANN, axis=1))  # power=1
        out[s : s + BLOCK_FRAMES] = mag @ _MELFB
    return out


def estimate(audio: np.ndarray, sr: int) -> tuple[float, float]:
    """(bpm, confidence) for a track. confidence = mean per-patch peak softmax."""
    mel = _melspectrogram(_resample_11025(audio, sr))
    if mel.shape[0] < PATCH:
        return 0.0, 0.0
    starts = range(0, mel.shape[0] - PATCH + 1, PATCH_HOP)
    patches = np.stack([mel[s : s + PATCH].T for s in starts])[:, :, :, None].astype(np.float32)
    # Mel/patch prep above is pure NumPy and stays parallel; only the session
    # build + inference are serialised -- see _lock.
    with _lock:
        sess = _session()
        inn, outn = _engine["inn"], _engine["outn"]
        soft = np.concatenate(  # per-PATCH_BATCH runs, not one giant run — see PATCH_BATCH
            [
                sess.run([outn], {inn: patches[i : i + PATCH_BATCH]})[0]
                for i in range(0, len(patches), PATCH_BATCH)
            ],
            axis=0,
        )  # (n_patches, 256)

    # Aggregate by AVERAGING the per-patch softmax distributions, then argmax. This
    # beats Essentia's default "majority" vote-of-argmaxes against the oracle
    # (96.7% vs 95.0% within 2%/octave) -- averaging is steadier when a track's
    # patches split across an octave. confidence = the averaged peak probability.
    dist = soft.mean(axis=0)  # (256,)
    cls = int(dist.argmax())
    return round(30.0 + cls * 256.0 / 255.0, 1), float(dist[cls])

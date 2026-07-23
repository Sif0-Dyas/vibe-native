"""Native audio decode matching Essentia's MonoLoader(sampleRate=16000) — the
Windows replacement that reproduces the oracle's 16 kHz mono audio.

ffmpeg is a RUNTIME prerequisite of the native build (winget install ffmpeg); the
Phase-4/5 app needs it on any machine it runs on (see tools/CONVERSION_NOTES.md).

The pipeline mirrors Essentia MonoLoader = AudioLoader -> MonoMixer -> Resample,
verified against Essentia's actual output on all 121 oracle tracks (cos > 0.999):
  1. ffmpeg decodes to native-rate float32 PCM (all channels).
  2. downmix to mono by AMPLITUDE AVERAGE (L+R)/2 — Essentia's MonoMixer 'mix'.
     (ffmpeg's own `-ac 1` uses an energy-preserving (L+R)/sqrt(2), 1/sqrt(2) too
     loud; getting this wrong shifts the whole log-mel — see CONVERSION_NOTES.)
  3. linear-interpolation resample to 16 kHz — Essentia's resampleQuality=4 maps
     to libsamplerate SRC_LINEAR. A small group-delay phase (RESAMPLE_PHASE, in
     input samples) is calibrated against Essentia's resampler; numpy-only, no
     samplerate/librosa dependency.
"""

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

SR = 16000
# Group-delay of Essentia's resampler in native-input samples, calibrated so the
# reproduced 16 kHz audio matches Essentia's; validated to cos > 0.999 (worst
# 0.99932) on all 121 oracle tracks at both 44.1 and 48 kHz. See CONVERSION_NOTES.
RESAMPLE_PHASE = -1.24


def _tool(name: str) -> str:
    exe = shutil.which(name)
    if exe:
        return exe
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / f"Microsoft/WinGet/Links/{name}.exe"
    if cand.exists():
        return str(cand)
    raise FileNotFoundError(f"{name} not found on PATH — run `winget install ffmpeg`")


def _probe(path) -> tuple[int, int]:
    import json

    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    s = json.loads(out)["streams"][0]
    return int(s["sample_rate"]), int(s["channels"])


def _linear_resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    step = sr_in / sr_out
    n_out = int(round(len(x) * sr_out / sr_in))
    pos = np.arange(n_out) * step + RESAMPLE_PHASE
    base = np.floor(pos)
    frac = pos - base
    i0 = np.clip(base.astype(np.int64), 0, len(x) - 1)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    return (1.0 - frac) * x[i0] + frac * x[i1]


def decode_mono(path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to `sr` Hz mono float32, matching Essentia MonoLoader.

    The RESAMPLE_PHASE calibration was fit for the 16 kHz genre path; the tempo
    (11025) and key (44100) paths reuse it but have loose acceptance (BPM 2%/octave,
    key exact-match), so the sub-sample offset is immaterial there."""
    src_sr, ch = _probe(path)
    raw = subprocess.run(
        [_tool("ffmpeg"), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(ch), "-"],
        capture_output=True, check=True,
    ).stdout
    a = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    mono = a if ch == 1 else a.reshape(-1, ch).mean(axis=1)  # (L+R)/2
    return _linear_resample(mono, src_sr, sr).astype(np.float32)


def decode_16k_mono(path) -> np.ndarray:
    """Decode to 16 kHz mono float32 (the genre/embedder path)."""
    return decode_mono(path, SR)

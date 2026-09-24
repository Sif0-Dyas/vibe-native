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
import subprocess  # nosec B404  # only runs ffmpeg/ffprobe with fixed arg lists, never a shell
from pathlib import Path

import numpy as np

from .paths import exe_dir

# On a frozen --windowed Windows build, each ffmpeg/ffprobe call would briefly
# flash a console window — hundreds of them during a batch scan, which also churns
# window handles and steals focus, and on its own can destabilise the app.
# CREATE_NO_WINDOW runs every child hidden. 0 on non-Windows (the flag is absent).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SR = 16000
# Group-delay of Essentia's resampler in native-input samples, calibrated so the
# reproduced 16 kHz audio matches Essentia's; validated to cos > 0.999 (worst
# 0.99932) on all 121 oracle tracks at both 44.1 and 48 kHz. See CONVERSION_NOTES.
RESAMPLE_PHASE = -1.24

# Wall-clock caps on the child processes. A corrupt or truncated file can leave
# ffmpeg/ffprobe blocked forever, which would pin a /batch worker for the rest of
# the scan. subprocess.run kills the child when the cap expires; the callers see a
# RuntimeError naming the file, which /batch reports as that file's failure line.
# A full decode of a long mix is seconds, not minutes; a probe is near-instant.
DECODE_TIMEOUT_S = 120
PROBE_TIMEOUT_S = 30


def _tool(name: str) -> str:
    exe = shutil.which(name)
    if exe:
        return exe
    # Packaged build: tools/prepare_dist.py drops ffmpeg/ffprobe next to the exe
    # (loose, or under an ffmpeg/ subdir) so the .exe never silently needs PATH ffmpeg.
    for cand in (exe_dir() / f"{name}.exe", exe_dir() / "ffmpeg" / f"{name}.exe"):
        if cand.is_file():
            return str(cand)
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / f"Microsoft/WinGet/Links/{name}.exe"
    if cand.exists():
        return str(cand)
    raise FileNotFoundError(
        f"{name} not found on PATH, next to the exe, or WinGet — install ffmpeg"
    )


def find_tool(name: str) -> str | None:
    """Locate ffmpeg/ffprobe (PATH, then exe-adjacent, then the WinGet Links dir);
    None if absent. The soft-fail companion to :func:`_tool` for callers that degrade
    gracefully when ffmpeg is missing (e.g. the segment-clip extractor)."""
    try:
        return _tool(name)
    except FileNotFoundError:
        return None


def _probe(path) -> tuple[int, int]:
    import json

    try:
        out = subprocess.run(  # nosec B603  # ffprobe from _tool(); args are a list (no shell), path is a local file
            [
                _tool("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            creationflags=NO_WINDOW,
            timeout=PROBE_TIMEOUT_S,
        ).stdout
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out after {PROBE_TIMEOUT_S} s on {path}") from e
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
    try:
        raw = subprocess.run(  # nosec B603  # ffmpeg from _tool(); args are a list (no shell), path is a local file
            [_tool("ffmpeg"), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(ch), "-"],
            capture_output=True,
            check=True,
            creationflags=NO_WINDOW,
            timeout=DECODE_TIMEOUT_S,
        ).stdout
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out after {DECODE_TIMEOUT_S} s decoding {path}") from e
    a = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    mono = a if ch == 1 else a.reshape(-1, ch).mean(axis=1)  # (L+R)/2
    return _linear_resample(mono, src_sr, sr).astype(np.float32)


def decode_16k_mono(path) -> np.ndarray:
    """Decode to 16 kHz mono float32 (the genre/embedder path)."""
    return decode_mono(path, SR)

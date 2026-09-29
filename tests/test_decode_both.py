"""decode_both == the two decodes it replaces, for mono, stereo and 6-channel input.

decode_both mixes to mono inside ffmpeg (a pan filter) and keeps float32; the
decodes it replaces mixed in numpy (float64 mean). Each channel here carries
different content, so a wrong weight or a dropped channel shows up. Needs ffmpeg;
skipped where it isn't installed (CI).
"""

import struct
import wave

import numpy as np
import pytest

from vibenative import decode

pytestmark = pytest.mark.skipif(
    not (decode.find_tool("ffmpeg") and decode.find_tool("ffprobe")), reason="needs ffmpeg"
)


def _wav(path, channels, rate=48000, seconds=3):
    t = np.arange(rate * seconds) / rate
    # a different tone and level per channel
    chans = [
        0.2 * (c + 1) / channels * np.sin(2 * np.pi * (110 * (c + 1)) * t) for c in range(channels)
    ]
    inter = np.stack(chans, axis=1).reshape(-1)
    pcm = np.clip(inter * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    return path


@pytest.mark.parametrize("channels", [1, 2, 6])
def test_decode_both_matches_the_decodes_it_replaces(tmp_path, channels):
    f = _wav(tmp_path / f"c{channels}.wav", channels)
    a16, a44 = decode.decode_both(f)
    ref16 = decode.decode_16k_mono(f)
    ref44 = decode.decode_mono(f, 44100)
    assert a16.dtype == np.float32 and a44.dtype == np.float32
    assert a16.shape == ref16.shape and a44.shape == ref44.shape
    # float mix vs float64 mean: equal for 1-2 channels, ~1e-8 for 6. An integer-domain
    # mix (pan on an int16 source without aformat=flt first) is off by ~1.5e-5.
    assert np.max(np.abs(a16 - ref16)) < 1e-6
    assert np.max(np.abs(a44 - ref44)) < 1e-6


def test_pan_filter_is_an_equal_weight_mean():
    assert decode._mono_pan(1) is None
    assert decode._mono_pan(2) == "pan=mono|c0=0.5*c0+0.5*c1"
    six = decode._mono_pan(6)
    assert six.startswith("pan=mono|c0=") and "<" not in six  # "=": no renormalising
    assert six.count("*c") == 6

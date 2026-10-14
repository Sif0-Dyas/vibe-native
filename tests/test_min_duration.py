"""The minimum-duration filter: files shorter than Settings.min_duration_s are
skipped before analysis -- by batch and by drag-and-drop -- counted, reported, and
never written to the library.

The suite's conftest turns the filter off (its fixtures are fractions of a
second long); every test here turns it on. The "real tracks" are 70-second WAVs:
long enough to pass, generated here, because tests never touch real user files.
"""

import io
import json
import struct
import wave
from contextlib import closing

import pytest

RATE = 8000


def _wav_bytes(seconds, level):
    buf = io.BytesIO()
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        n = int(seconds * RATE)
        # a slow ramp so every file hashes differently and isn't silence
        w.writeframes(struct.pack(f"<{n}h", *((level + i % 400) for i in range(n))))
    return buf.getvalue()


def _library_size():
    from vibenative.db import db

    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]


@pytest.fixture()
def music(tmp_path):
    """Six 5-second clips and two 70-second tracks, in nested folders."""
    root = tmp_path / "music"
    (root / "clips").mkdir(parents=True)
    (root / "album").mkdir()
    for i in range(6):
        (root / "clips" / f"clip{i}.wav").write_bytes(_wav_bytes(5, 100 * (i + 1)))
    for i in range(2):
        (root / "album" / f"track{i}.wav").write_bytes(_wav_bytes(70, 3000 + 500 * i))
    return root


@pytest.fixture()
def minimum(use_settings):
    return use_settings(min_duration_s=60.0)


def test_probe_duration_reads_a_wav_with_or_without_ffprobe(tmp_path, monkeypatch):
    from vibenative import metadata

    f = tmp_path / "five.wav"
    f.write_bytes(_wav_bytes(5, 100))
    assert metadata.probe_duration(f) == pytest.approx(5.0, abs=0.05)
    monkeypatch.setattr(metadata, "find_tool", lambda name: None)  # no ffprobe at all
    assert metadata.probe_duration(f) == pytest.approx(5.0, abs=0.01)
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio")
    assert metadata.probe_duration(junk) is None  # unknown is not "short"


def test_batch_skips_short_files_and_reports_them(client, minimum, music):
    lines = client.post("/api/v1/batch", json={"path": str(music)}).data.decode().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    final = rows[-1]
    assert final == {"done": True, "cancelled": False, "processed": 8, "total": 8, "short": 6}

    short = [r for r in rows if r.get("short") is True]  # the final line counts them
    assert sorted(r["filename"] for r in short) == [f"clip{i}.wav" for i in range(6)]
    assert all(r["ok"] is False and r["duration"] == pytest.approx(5.0, abs=0.1) for r in short)
    analysed = [r for r in rows if r.get("ok")]
    assert sorted(r["filename"] for r in analysed) == ["track0.wav", "track1.wav"]
    assert _library_size() == 2  # the clips were never written


def test_a_dropped_short_file_gets_a_notice_not_a_row(client, minimum):
    clip = {"file": (io.BytesIO(_wav_bytes(5, 700)), "clip.wav")}
    r = client.post("/api/v1/analyze", data=clip, content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False and body["short"] is True
    assert body["duration"] == pytest.approx(5.0, abs=0.1) and body["min_duration"] == 60.0
    assert _library_size() == 0

    track = {"file": (io.BytesIO(_wav_bytes(70, 900)), "track.wav")}
    r = client.post("/api/v1/analyze", data=track, content_type="multipart/form-data")
    assert r.status_code == 200 and "hash" in r.get_json()
    assert _library_size() == 1


def test_zero_turns_the_filter_off(client, use_settings, music):
    use_settings(min_duration_s=0.0)
    lines = client.post("/api/v1/batch", json={"path": str(music)}).data.decode().splitlines()
    final = json.loads(lines[-1])
    assert final == {"done": True, "cancelled": False, "processed": 8, "total": 8}  # no "short"
    assert _library_size() == 8


def test_options_changes_it_at_once_and_saves_it(client, minimum, settings):
    from vibenative.paths import settings_ini

    assert client.get("/api/v1/status").get_json()["min_duration_s"] == 60.0
    r = client.post("/api/v1/min-duration", json={"seconds": 3})
    assert r.status_code == 200 and r.get_json()["min_duration_s"] == 3
    assert client.get("/api/v1/status").get_json()["min_duration_s"] == 3
    assert "min_duration_s = 3" in settings_ini().read_text(encoding="utf-8")

    # in effect without a restart: a 5-second clip now passes
    clip = {"file": (io.BytesIO(_wav_bytes(5, 1100)), "clip.wav")}
    body = client.post("/api/v1/analyze", data=clip, content_type="multipart/form-data").get_json()
    assert "hash" in body and not body.get("short")

    for bad in ({}, {"seconds": "x"}, {"seconds": -1}, {"seconds": 99999}):
        assert client.post("/api/v1/min-duration", json=bad).status_code == 400


def test_an_env_var_pins_it(client, use_settings):
    use_settings(min_duration_s=45.0, min_duration_from_env=True)
    r = client.post("/api/v1/min-duration", json={"seconds": 10})
    assert r.status_code == 409 and "VIBE_MIN_DURATION" in r.get_json()["error"]
    status = client.get("/api/v1/status").get_json()
    assert status["min_duration_s"] == 45.0 and status["min_duration_from_env"] is True


def test_settings_from_env_ini_and_default(tmp_path):
    from vibenative.settings import Settings

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    base = {"VIBE_CONFIG_DIR": str(cfg), "GENRE_DB": str(tmp_path / "x.db")}
    s = Settings.from_env(base)
    assert s.min_duration_s == 60.0 and s.min_duration_from_env is False

    (cfg / "settings.ini").write_text("[vibenative]\nmin_duration_s = 20\n", encoding="utf-8")
    assert Settings.from_env(base).min_duration_s == 20.0

    s = Settings.from_env({**base, "VIBE_MIN_DURATION": "45"})  # the env var wins
    assert s.min_duration_s == 45.0 and s.min_duration_from_env is True
    assert Settings.from_env({**base, "VIBE_MIN_DURATION": "nope"}).min_duration_s == 60.0
    assert Settings.from_env({**base, "VIBE_MIN_DURATION": "-5"}).min_duration_s == 0.0

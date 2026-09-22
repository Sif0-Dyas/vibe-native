"""Cue point + energy detection (cues.py) on synthetic audio with a known
structure, and the routes / export that carry the result.

The detector is heuristic, so these tests pin what a DJ would notice if it
went wrong -- a drop flagged in the wrong section, a grid that doesn't sit on
the beat, a quiet track rated hotter than a loud one -- not exact numbers."""

import io
import wave

import numpy as np
import pytest

from vibenative import cues

SR = 11025
BPM = 128.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
PHASE = 0.1  # the first beat lands 100 ms in


def _kick(t, f0=60.0):
    """A short decaying low sine: the kick that marks every beat."""
    return np.sin(2 * np.pi * f0 * t) * np.exp(-t * 18.0)


def synth_track(rng, level_db=-8.0, quiet_db=-28.0, sections=None):
    """A 4/4 track at 128 BPM. ``sections`` = [(seconds, kind)] where kind is
    'quiet' (soft beats), 'loud' (kick + noise at level_db), 'pad' (no beats,
    a sustained tone) or 'silence'."""
    sections = sections or [
        (8 * BAR, "quiet"),  # intro, 8 bars
        (16 * BAR, "loud"),  # drop 1
        (8 * BAR, "pad"),  # breakdown
        (16 * BAR, "loud"),  # drop 2
        (8 * BAR, "quiet"),  # outro
        (2.0, "silence"),
    ]
    total = sum(s for s, _ in sections)
    n = int(total * SR)
    x = np.zeros(n, dtype=np.float64)
    t = np.arange(n) / SR
    # beats through the whole track (muted where a section has none)
    beat_times = PHASE + BEAT * np.arange(int(total / BEAT))
    kick_len = int(0.25 * SR)
    kick = _kick(np.arange(kick_len) / SR)
    click = np.zeros(kick_len)
    click[: int(0.004 * SR)] = 1.0  # a 4 ms tick for the quiet parts
    pos = 0.0
    for secs, kind in sections:
        a, b = int(pos * SR), int((pos + secs) * SR)
        if kind == "loud":
            gain = 10 ** (level_db / 20)  # noise RMS = level_db, like a compressed master
            x[a:b] += rng.standard_normal(b - a) * gain
            for bt in beat_times[(beat_times >= pos) & (beat_times < pos + secs)]:
                i = int(bt * SR)
                x[i : i + kick_len] += kick[: max(0, min(kick_len, n - i))] * gain * 1.2
        elif kind == "quiet":
            gain = 10 ** (quiet_db / 20)
            x[a:b] += rng.standard_normal(b - a) * gain * 0.3
            for bt in beat_times[(beat_times >= pos) & (beat_times < pos + secs)]:
                i = int(bt * SR)
                x[i : i + kick_len] += click[: max(0, min(kick_len, n - i))] * gain * 2
        elif kind == "pad":
            gain = 10 ** ((quiet_db + 4) / 20)
            x[a:b] += np.sin(2 * np.pi * 220.0 * t[a:b]) * gain
        pos += secs
    # brickwall at full scale, the way a club master is limited
    return np.clip(x, -1.0, 1.0).astype(np.float32), total


@pytest.fixture(scope="module")
def track():
    rng = np.random.default_rng(3)
    x, total = synth_track(rng)
    return x, total, cues.analyze(x, SR, BPM)


def test_result_shape(track):
    _, total, r = track
    assert set(r) == {"energy", "energy_curve", "energy_hop", "grid", "cues"}
    assert 1 <= r["energy"] <= 10
    assert r["energy_hop"] == cues.ENERGY_HOP
    assert len(r["energy_curve"]) == int(np.ceil(total / cues.ENERGY_HOP))
    assert all(0.0 <= v <= 1.0 for v in r["energy_curve"])
    for c in r["cues"]:
        assert set(c) == {"t", "type", "label", "bar", "energy"}
        assert 0.0 <= c["t"] <= total
        assert 1 <= c["energy"] <= 10
    assert len(r["cues"]) <= cues.MAX_CUES


def test_grid_sits_on_the_beat(track):
    _, _, r = track
    g = r["grid"]
    assert g is not None and g["confidence"] >= cues.GRID_MIN_CONFIDENCE
    assert g["bpm"] == pytest.approx(BPM, abs=0.2)
    # the grid offset is SOME beat of the click train (the bar phase may have
    # moved it by whole beats), within a frame of a true beat
    k = (g["offset"] - PHASE) / BEAT
    assert abs(k - round(k)) * BEAT < 0.03


def test_cues_land_on_the_structure(track):
    _, _, r = track
    by = {}
    for c in r["cues"]:
        by.setdefault(c["type"], []).append(c["t"])
    # intro = bar 1 at the start; end = the last audible beat before the silence
    assert by["start"][0] < BAR
    assert by["end"][0] == pytest.approx(56 * BAR, abs=2 * BEAT)
    # both drops, each within a bar of where the loud section really starts
    assert len(by["drop"]) == 2
    assert by["drop"][0] == pytest.approx(8 * BAR, abs=BAR)
    assert by["drop"][1] == pytest.approx(32 * BAR, abs=BAR)
    # the breakdown between them, and the outro after the last drop
    assert by["break"][0] == pytest.approx(24 * BAR, abs=BAR)
    assert by["outro"][0] == pytest.approx(48 * BAR, abs=BAR)
    # labels: drops numbered in time order
    labels = [c["label"] for c in r["cues"] if c["type"] == "drop"]
    assert labels == ["Drop 1", "Drop 2"]
    # cues are on the grid: whole beats from the intro
    t0 = by["start"][0]
    for c in r["cues"]:
        k = (c["t"] - t0) / BEAT
        assert abs(k - round(k)) < 0.02
    # bar numbers count from the intro
    assert [c["bar"] for c in r["cues"] if c["type"] == "start"] == [1]
    assert by["drop"] == sorted(by["drop"])


def test_cue_energy_follows_the_section(track):
    _, _, r = track
    drops = [c["energy"] for c in r["cues"] if c["type"] == "drop"]
    quiet = [c["energy"] for c in r["cues"] if c["type"] in ("start", "break", "outro")]
    assert min(drops) > max(quiet)


def test_energy_level_orders_loud_over_quiet():
    rng = np.random.default_rng(5)
    loud, _ = synth_track(rng, level_db=-6.0)
    soft, _ = synth_track(rng, level_db=-8.0, sections=[(30 * BAR, "quiet"), (1.0, "silence")])
    e_loud = cues.analyze(loud, SR, BPM)["energy"]
    e_soft = cues.analyze(soft, SR, BPM)["energy"]
    assert e_loud >= 8
    assert e_soft <= 3
    # tempo nudges, octave-blind: 87 and 174 BPM reads of the same audio agree
    assert cues.energy_level([0.6] * 10, 87.0) == cues.energy_level([0.6] * 10, 174.0)
    assert cues.energy_level([0.6] * 10, 174.0) >= cues.energy_level([0.6] * 10, 120.0)


def test_no_bpm_means_no_grid_but_still_cues():
    rng = np.random.default_rng(9)
    x, _ = synth_track(rng)
    r = cues.analyze(x, SR, None)
    assert r["grid"] is None
    assert all(c["bar"] is None for c in r["cues"])
    assert any(c["type"] == "drop" for c in r["cues"])


def test_silence_and_short_audio_do_not_crash():
    r = cues.analyze(np.zeros(SR * 3, dtype=np.float32), SR, 128.0)
    assert r["energy"] == 1 and r["grid"] is None
    r = cues.analyze(np.zeros(10, dtype=np.float32), SR, 128.0)
    assert r["cues"] == [] and len(r["energy_curve"]) >= 1
    r = cues.analyze(np.ones(44100, dtype=np.float32), 44100, None)
    assert 1 <= r["energy"] <= 10


def test_resample_from_44k_matches_native_rate():
    rng = np.random.default_rng(11)
    x, _ = synth_track(rng)
    # upsample 4x by repetition and let analyze() bring it back down
    x44 = np.repeat(x, 4)
    a = cues.analyze(x, SR, BPM)
    b = cues.analyze(x44, 44100, BPM)
    assert a["energy"] == b["energy"]
    assert [c["type"] for c in a["cues"]] == [c["type"] for c in b["cues"]]


# --- routes -----------------------------------------------------------------


def _wav_bytes(x, sr=SR):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_analyze_payload_carries_dj_features(client):
    data = {"file": (io.BytesIO(_wav_bytes(np.zeros(SR))), "t.wav")}
    r = client.post("/analyze", data=data, content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200
    assert 1 <= j["energy"] <= 10
    assert j["cues"] and j["cues"][0]["type"] == "start"
    assert j["grid"]["bpm"] == j["bpm"]
    assert len(j["energy_curve"]) == int(j["duration"]) + 1
    # and it comes back the same on the cache hit
    r2 = client.post(
        "/analyze",
        data={"file": (io.BytesIO(_wav_bytes(np.zeros(SR))), "t.wav")},
        content_type="multipart/form-data",
    )
    assert r2.get_json()["cues"] == j["cues"]
    assert client.get(f"/cues/{j['hash']}").get_json()["energy"] == j["energy"]


def test_cues_route_fills_in_an_older_track(client, tmp_path):
    """A track analysed before cue detection existed has no cues in its payload;
    GET /cues runs the real detector on its file and stores the result."""
    from contextlib import closing

    from conftest import seed_track
    from vibenative.db import _db_lock, cache_get, db

    rng = np.random.default_rng(2)
    x, _ = synth_track(rng)
    p = tmp_path / "old.wav"
    p.write_bytes(_wav_bytes(x))
    h = seed_track("old" * 10, {"styles": [], "bpm": BPM, "duration": 100.0})
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute("UPDATE tracks SET filepath=? WHERE hash=?", (str(p), h))

    r = client.get(f"/cues/{h}")
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["grid"]["bpm"] == pytest.approx(BPM, abs=0.2)
    assert any(c["type"] == "drop" for c in j["cues"])
    # stored: the payload now carries it, and the library row shows the level
    assert cache_get(h)["energy"] == j["energy"]
    assert client.get(f"/track/{h}").get_json()["cues"] == j["cues"]
    lib = {t["hash"]: t for t in client.get("/library").get_json()}
    assert lib[h]["energy"] == j["energy"]


def test_cues_route_404s_without_audio(client):
    from conftest import seed_track

    h = seed_track("nofile" * 6, {"styles": [], "bpm": 128.0})
    assert client.get(f"/cues/{h}").status_code == 404
    assert client.get("/cues/unknown").status_code == 404


def test_cues_upload_route(client):
    from conftest import seed_track
    from vibenative.db import file_hash

    rng = np.random.default_rng(4)
    x, _ = synth_track(rng)
    wav = _wav_bytes(x)
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "u.wav"
    tmp.write_bytes(wav)
    h = seed_track(file_hash(tmp), {"styles": [], "bpm": BPM})
    # the wrong audio is refused
    bad = client.post(
        f"/cues/{h}",
        data={"file": (io.BytesIO(_wav_bytes(np.zeros(SR))), "x.wav")},
        content_type="multipart/form-data",
    )
    assert bad.status_code == 400
    ok = client.post(
        f"/cues/{h}", data={"file": (io.BytesIO(wav), "u.wav")}, content_type="multipart/form-data"
    )
    assert ok.status_code == 200
    assert ok.get_json()["grid"] is not None


# --- Rekordbox export -------------------------------------------------------


def test_rekordbox_xml_carries_grid_cues_and_energy():
    from vibenative import ratings

    t = {
        "hash": "h1",
        "title": "T",
        "artist": "A",
        "filepath": r"C:\m\t.mp3",
        "bpm": 128.4,
        "energy": 7,
        "grid": {"bpm": 128.05, "offset": 0.512, "confidence": 5.0},
        "cues": [
            {"t": 0.512, "type": "start", "label": "Intro", "bar": 1, "energy": 3},
            {"t": 60.5, "type": "drop", "label": "Drop 1", "bar": 33, "energy": 8},
        ],
    }
    xml = ratings.playlist_xml("p", [t], {"h1": {"stars": 4, "grade": "A", "note": "peak"}})
    assert 'Comments="Energy 7 - A - peak"' in xml
    assert '<TEMPO Inizio="0.512" Bpm="128.05" Metro="4/4" Battito="1"/>' in xml
    assert '<POSITION_MARK Name="Drop 1 (E8)" Type="0" Start="60.5" Num="-1"/>' in xml
    assert "<TRACK " in xml and "</TRACK>" in xml
    # a track without any of it still exports as a self-closing row
    plain = ratings.playlist_xml("p", [{"hash": "h2", "filepath": r"C:\m\u.mp3"}])
    assert "</TRACK>" not in plain and "POSITION_MARK" not in plain

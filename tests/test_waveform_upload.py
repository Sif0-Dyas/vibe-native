"""Tests for building a track's detailed waveform from an uploaded copy.

The Analyzer draws a coarse stored envelope immediately, then replaces it with
the DAW-style min/max/rms waveform. That upgrade could only ever reach tracks the
server could reach: one with a cached waveform, or one with a file path on disk
to decode. A track dragged in and analysed without being linked to a folder had
neither -- so it was stuck on the coarse envelope permanently, with no sequence
of actions that could ever fix it, however many times it was re-added.

The browser is holding the audio in exactly those cases, so it can send it. These
tests are mostly about what that upload is *not* allowed to be: a way to have the
server decode arbitrary files, or to file one track's waveform under another's
name.
"""

import io
import struct
import wave


def _wav(sample=0):
    buf = io.BytesIO()
    w = wave.open(buf, "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(struct.pack("<800h", *([sample] * 800)))
    w.close()
    return buf.getvalue()


def _analyze(client, audio, name="drop.wav"):
    r = client.post(
        "/analyze",
        data={"file": (io.BytesIO(audio), name)},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    return r.get_json()["hash"]


def _upload_waveform(client, h, audio, name="drop.wav"):
    return client.post(
        f"/waveform/{h}",
        data={"file": (io.BytesIO(audio), name)},
        content_type="multipart/form-data",
    )


def _forget_waveform(h):
    """Drop the waveform analysis cached at analysis time, leaving the track in
    the state this endpoint exists for: in the library, with no waveform and no
    file on disk."""
    from contextlib import closing

    from vibenative.db import db

    with closing(db()) as conn, conn as c:
        c.execute("DELETE FROM waveform_cache WHERE hash=?", (h,))
        c.execute("UPDATE tracks SET filepath=NULL WHERE hash=?", (h,))


def test_a_track_with_no_file_and_no_waveform_cannot_get_one_by_asking(client):
    """The starting position: this is the gap the upload closes."""
    audio = _wav(11)
    h = _analyze(client, audio)
    _forget_waveform(h)
    assert client.get(f"/waveform/{h}").status_code == 404


def test_uploading_the_audio_builds_the_waveform(client):
    audio = _wav(11)
    h = _analyze(client, audio)
    _forget_waveform(h)

    r = _upload_waveform(client, h, audio)
    assert r.status_code == 200
    mm = r.get_json()
    assert mm["max"] and len(mm["max"]) == len(mm["min"]) == len(mm["rms"])


def test_the_result_is_cached_so_it_happens_once(client):
    audio = _wav(11)
    h = _analyze(client, audio)
    _forget_waveform(h)
    built = _upload_waveform(client, h, audio).get_json()

    # The plain GET now answers, without the file being sent again.
    r = client.get(f"/waveform/{h}")
    assert r.status_code == 200
    assert r.get_json() == built


def test_audio_that_is_not_that_track_is_refused(client):
    """The upload names the track it is for. If the two could disagree, a row
    would quietly draw someone else's audio."""
    h = _analyze(client, _wav(11), "one.wav")
    _forget_waveform(h)
    r = _upload_waveform(client, h, _wav(22), "two.wav")
    assert r.status_code == 400
    assert client.get(f"/waveform/{h}").status_code == 404   # nothing was stored


def test_an_unknown_track_is_refused(client):
    """This must not become a way to have the server decode uploads under any
    key the caller invents."""
    r = _upload_waveform(client, "0" * 40, _wav(11))
    assert r.status_code == 404


def test_a_missing_upload_is_a_bad_request_not_a_crash(client):
    h = _analyze(client, _wav(11))
    _forget_waveform(h)
    r = client.post(f"/waveform/{h}", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_uploading_when_it_is_already_cached_just_returns_it(client):
    """Two tabs can race on the same track; the second one has nothing to do."""
    audio = _wav(11)
    h = _analyze(client, audio)           # analysis already cached a waveform
    r = _upload_waveform(client, h, audio)
    assert r.status_code == 200
    assert r.get_json() == client.get(f"/waveform/{h}").get_json()

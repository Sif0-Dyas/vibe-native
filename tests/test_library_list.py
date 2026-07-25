"""The /library listing endpoint (Library tab data source).

/library returns a lean row per cached track. NOTE: it takes NO query params —
pagination, sort, search, column selection, and grouping are ALL done client-side
in library.js (against the returned rows). The only server-side request args in
this blueprint are numeric (`k`, `threshold`), so there is no user-controlled SQL
identifier and thus no sort-injection surface; the tests below document that.
FAKE mode, throwaway DB (see conftest.py).
"""

import io
import json
import struct
import wave


def _tiny_wav_bytes(sample=0):
    buf = io.BytesIO()
    w = wave.open(buf, "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(struct.pack("<800h", *([sample] * 800)))
    w.close()
    return buf.getvalue()


def _analyze_upload(client, name, sample):
    # a browser-dropped upload: no server-side filepath is stored
    data = {"file": (io.BytesIO(_tiny_wav_bytes(sample=sample)), name)}
    return client.post("/analyze", data=data, content_type="multipart/form-data").get_json()["hash"]


def _batch_one(client, tmp_path, name, sample):
    # a folder scan: the cached track keeps a server-side filepath
    music = tmp_path / "lib"
    music.mkdir(exist_ok=True)
    (music / name).write_bytes(_tiny_wav_bytes(sample=sample))
    lines = client.post("/batch", json={"path": str(music)}).data.decode().splitlines()
    results = [json.loads(x) for x in lines if x.strip()]
    return next(r["hash"] for r in results if r.get("hash"))


def test_library_empty(client):
    r = client.get("/library")
    assert r.status_code == 200
    assert r.get_json() == []


def test_library_lists_tracks_with_expected_shape(client):
    hashes = {_analyze_upload(client, f"t{i}.wav", i + 1) for i in range(3)}
    rows = client.get("/library").get_json()
    assert {r["hash"] for r in rows} == hashes
    for row in rows:
        for key in (
            "hash",
            "title",
            "filename",
            "artist",
            "style",
            "bpm",
            "key",
            "scale",
            "camelot",
            "duration",
            "has_file",
            "created",
        ):
            assert key in row, f"missing {key} in library row"


def test_library_ordered_newest_first(client):
    # rows come back ordered by `created` descending; assert the ordering property
    # itself (robust to the clock resolution that decides which insert is 'newer').
    for i in range(3):
        _analyze_upload(client, f"o{i}.wav", i + 1)
    createds = [r["created"] for r in client.get("/library").get_json()]
    assert createds == sorted(createds, reverse=True)


def test_library_has_file_flag(client, tmp_path):
    # a folder-scanned track has a server-side file; a dropped upload does not
    scanned = _batch_one(client, tmp_path, "scanned.wav", sample=7)
    dropped = _analyze_upload(client, "dropped.wav", sample=8)
    by_hash = {r["hash"]: r for r in client.get("/library").get_json()}
    assert by_hash[scanned]["has_file"] is True
    assert by_hash[dropped]["has_file"] is False


def test_library_drops_heavy_arrays(client):
    # the listing is deliberately lean: the big segments/waveform arrays that the
    # stored payload carries must NOT be in the row (that's what keeps it cheap).
    _analyze_upload(client, "lean.wav", sample=2)
    row = client.get("/library").get_json()[0]
    assert "segments" not in row and "waveform" not in row and "frames" not in row


def test_library_ignores_unknown_query_params_no_injection(client):
    # /library takes no server-side sort/search params (that's all client-side), so
    # a bogus/hostile 'sort' value is simply ignored — it can't reach SQL as an
    # identifier. Prove it: the response is unchanged and never errors.
    _analyze_upload(client, "a.wav", sample=1)
    _analyze_upload(client, "b.wav", sample=2)
    baseline = client.get("/library").get_json()

    for hostile in ("hash); DROP TABLE tracks;--", "bpm", "notacolumn", "1=1"):
        r = client.get("/library", query_string={"sort": hostile, "q": hostile, "page": "99"})
        assert r.status_code == 200
        assert {row["hash"] for row in r.get_json()} == {row["hash"] for row in baseline}

    # and the tracks table is still intact after the injection-shaped input
    from contextlib import closing

    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        assert c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 2

"""One style per track, everywhere.

style.dominant_style is the single precedence chain (override -> weight
adjustments -> relabel -> salience -> styles[0]). /library reads it from the
``tracks.style`` column, the map and /similar compute it from the payload, and
the misread check (insight) uses it for every track and neighbour. These tests
put one track at each tier and check that all of them name the same style --
and that migration 11 fills the column with exactly what the function says.
"""

import json
import sqlite3

import numpy as np
import pytest

from vibenative import db, insight
from vibenative.settings import current
from vibenative.style import dominant_read, dominant_style

# styles[0] (what v9 put in the column) deliberately disagrees with salience.
BASE = {
    "salience": [{"style": "Techno", "score": 0.6}, {"style": "House", "score": 0.3}],
    "styles": [{"style": "Trance", "score": 0.5}, {"style": "Techno", "score": 0.4}],
    "bpm": 128,
}
RELABELLED = dict(BASE, relabel={"styles": [{"style": "Chillhop", "score": 0.9}]})


def _emb(seed):
    return np.random.default_rng(seed).standard_normal(1280).astype(np.float32)


def test_the_chain():
    assert dominant_style(BASE) == "Techno"  # salience beats styles[0]
    assert dominant_style({"styles": BASE["styles"]}) == "Trance"
    assert dominant_style(RELABELLED) == "Chillhop"
    assert dominant_style(dict(BASE, weights={"House": 3})) == "House"
    assert dominant_style(dict(RELABELLED, weights={"House": 3}, override="Dubstep")) == "Dubstep"
    assert dominant_read(dict(BASE, override="Dubstep")) == ("Dubstep", 1.0)
    assert dominant_read({}) == (None, 0.0) and dominant_style(None) is None


@pytest.fixture()
def library(client):
    """Five tracks with embeddings: one per tier (override, weights, relabel),
    set the way the app sets them, plus two plain ones. Returns {hash: expected}."""
    for i, (h, p) in enumerate(
        [("ovr", BASE), ("wts", BASE), ("rel", RELABELLED), ("pl1", BASE), ("pl2", BASE)]
    ):
        db.cache_put(h * 8, f"{h}.mp3", "", h, p, _emb(i))
    assert client.post("/override/" + "ovr" * 8, json={"genre": "Dubstep"}).status_code == 200
    r = client.post("/weights/" + "wts" * 8, json={"steps": {"House": 3}})
    assert r.status_code == 200, r.get_json()
    return {
        "ovr" * 8: "Dubstep",
        "wts" * 8: "House",
        "rel" * 8: "Chillhop",
        "pl1" * 8: "Techno",
        "pl2" * 8: "Techno",
    }


def test_every_view_reports_the_same_style(client, library, monkeypatch):
    # the column /library reads
    listed = {t["hash"]: t["style"] for t in client.get("/library").get_json()}
    assert {h: listed[h] for h in library} == library

    # /similar computes it from the payload
    for h in library:
        others = {t["hash"]: t["style"] for t in client.get(f"/similar/{h}?k=10").get_json()}
        assert others == {k: v for k, v in library.items() if k != h}

    # the map's nodes
    nodes = {n["hash"]: n["style"] for n in client.get("/map").get_json()["nodes"]}
    assert {h: nodes[h] for h in library} == library

    # the misread check: every track's own style and every neighbour's
    seen = {}
    real_score = insight._score

    def spy(top_style, top_conf, neighbours):
        seen.setdefault("tops", []).append(top_style)
        seen.setdefault("neighbours", set()).update(s for _sim, s in neighbours)
        return real_score(top_style, top_conf, neighbours)

    monkeypatch.setattr(insight, "_score", spy)
    insight.audit()
    assert sorted(seen["tops"]) == sorted(library.values())
    assert seen["neighbours"] <= set(library.values())


def test_the_column_follows_every_payload_write(client, library):
    conn = sqlite3.connect(current().db_path)
    try:
        rows = conn.execute("SELECT hash, payload, style FROM tracks").fetchall()
    finally:
        conn.close()
    for h, payload, style in rows:
        assert style == dominant_style(json.loads(payload)) == library[h], h

    # undoing the override puts the track back on its automatic read
    from vibenative.repo import tracks as tracks_repo

    def drop_override(payload):
        p = json.loads(payload)
        p.pop("override")
        return p

    tracks_repo.update_payload("ovr" * 8, drop_override)
    listed = {t["hash"]: t["style"] for t in client.get("/library").get_json()}
    assert listed["ovr" * 8] == "Techno"


def _v10_library(path, payloads):
    """A library as v10 left it: every migration up to 10 applied, the style
    column holding what v9 put there (styles[0])."""
    conn = sqlite3.connect(path)
    for version, migrate in db.MIGRATIONS:
        if version <= 10:
            migrate(conn)
    conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version(version) VALUES(10)")
    for h, p in payloads.items():
        raw = p if isinstance(p, str) else json.dumps(p)
        conn.execute(
            "INSERT INTO tracks(hash, filename, filepath, title, payload, embedding, created) "
            "VALUES(?,?,?,?,?,?,?)",
            (h, f"{h[:4]}.mp3", "", "t", raw, None, 0.0),
        )
    db._migration_9(conn)  # the v9 values, as an upgraded library has them
    conn.commit()
    conn.close()


def test_migration_11_backfills_the_dominant_style(tmp_path, use_settings):
    payloads = {
        "a" * 40: dict(BASE, override="Dubstep"),
        "b" * 40: dict(BASE, weights={"House": 3}),
        "c" * 40: RELABELLED,
        "d" * 40: BASE,
        "e" * 40: {"styles": [{"style": "Techno"}]},
        "f" * 40: {},
        "g" * 40: "{not json",
    }
    path = tmp_path / "v10.db"
    _v10_library(path, payloads)
    conn = sqlite3.connect(path)
    before = dict(conn.execute("SELECT hash, style FROM tracks"))
    conn.close()
    assert before["a" * 40] == "Trance"  # v9 ignored the override

    use_settings(db_path=path)
    db.init_db()  # runs migration 11

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 11
        after = dict(conn.execute("SELECT hash, style FROM tracks"))
    finally:
        conn.close()
    for h, p in payloads.items():
        if isinstance(p, dict):
            assert after[h] == dominant_style(p), h
    assert after["g" * 40] == before["g" * 40]  # unparseable: column left alone
    db.init_db()  # idempotent

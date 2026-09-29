"""Tests for retroactive re-labelling.

Runs against a scratch database with a stubbed classifier -- the point is the
bookkeeping (what gets written, what is preserved, what takes precedence), not
the model. A fake head lets a test say "now the head thinks everything is
Chillhop" and assert the library follows.
"""

import json
import sqlite3

import numpy as np
import pytest

SCHEMA = """
CREATE TABLE tracks(hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
                    payload TEXT, embedding BLOB, created REAL, style TEXT);
"""

LABELS = ["Electronic---House", "Electronic---Techno", "Electronic---Dubstep"]


def _emb(seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal(1280).astype(np.float32).tobytes()


@pytest.fixture
def rl(tmp_path, monkeypatch, use_settings):
    dbfile = tmp_path / "lib.db"
    con = sqlite3.connect(dbfile)
    con.executescript(SCHEMA)
    rows = [
        (
            "h1",
            "House Track",
            json.dumps(
                {
                    "salience": [{"style": "House", "score": 0.9}],
                    "styles": [{"style": "House", "score": 0.5}],
                }
            ),
            _emb(1),
        ),
        (
            "h2",
            "Techno Track",
            json.dumps({"salience": [{"style": "Techno", "score": 0.8}]}),
            _emb(2),
        ),
        (
            "h3",
            "Overridden",
            json.dumps({"override": "Trance", "salience": [{"style": "House", "score": 0.7}]}),
            _emb(3),
        ),
    ]
    for h, title, payload, blob in rows:
        con.execute(
            "INSERT INTO tracks(hash,filename,filepath,title,payload,embedding,created)"
            " VALUES(?,?,?,?,?,?,0)",
            (h, f"{h}.mp3", "", title, payload, blob),
        )
    con.commit()
    con.close()

    use_settings(db_path=dbfile)
    from vibenative import relabel

    monkeypatch.setattr(relabel, "_head_id", lambda: "custom:test")
    return relabel


def fake_engine(winner):
    """An engine whose classifier always favours `winner`."""
    idx = [x.split("---", 1)[1] for x in LABELS].index(winner)

    def classifier(v):
        p = np.full((1, len(LABELS)), 0.05, dtype=np.float32)
        p[0, idx] = 0.9
        return p

    return {"labels": LABELS, "classifier": classifier}


@pytest.fixture
def head(monkeypatch):
    """Point relabel at a fake head; returns a setter to change its opinion."""

    def use(winner):
        from vibenative import analysis

        monkeypatch.setattr(analysis, "get_engine", lambda: fake_engine(winner))

    return use


def _payload(rl_mod, h):
    from vibenative.settings import current

    with sqlite3.connect(current().db_path) as c:
        return json.loads(c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()[0])


# --- preview ------------------------------------------------------------------
def test_preview_reports_changes_without_writing(rl, head):
    head("Dubstep")
    before = _payload(rl, "h1")
    out = rl.preview()
    assert out["changed"] >= 1
    assert _payload(rl, "h1") == before  # nothing written
    assert all(e["to"] == "Dubstep" for e in out["examples"])


def test_preview_counts_unchanged_when_the_head_agrees(rl, head):
    head("House")
    out = rl.preview()
    # h1 already reads House; h3 is overridden and skipped entirely
    assert out["unchanged"] >= 1


# --- apply --------------------------------------------------------------------
def test_apply_writes_a_relabel_and_preserves_the_original_read(rl, head):
    head("Dubstep")
    rl.apply()
    p = _payload(rl, "h1")
    assert p["relabel"]["styles"][0]["style"] == "Dubstep"
    assert p["relabel"]["method"] == "mean-embedding"
    assert p["relabel"]["head"] == "custom:test"
    # the originally analysed read is untouched
    assert p["salience"][0]["style"] == "House"
    assert p["styles"][0]["style"] == "House"


def test_apply_never_touches_a_manual_override(rl, head):
    head("Dubstep")
    out = rl.apply()
    assert out["skipped_override"] == 1
    assert "relabel" not in _payload(rl, "h3")


def test_apply_is_idempotent_and_re_runnable(rl, head):
    head("Dubstep")
    rl.apply()
    head("Techno")
    rl.apply()  # a newer head replaces, not appends
    p = _payload(rl, "h1")
    assert p["relabel"]["styles"][0]["style"] == "Techno"
    assert isinstance(p["relabel"]["styles"], list)


def test_scores_are_normalised_over_the_kept_entries(rl, head):
    head("Dubstep")
    rl.apply()
    total = sum(s["score"] for s in _payload(rl, "h1")["relabel"]["styles"])
    assert total == pytest.approx(1.0, abs=0.01)


# --- revert -------------------------------------------------------------------
def test_revert_restores_the_original_reads(rl, head):
    head("Dubstep")
    before = _payload(rl, "h1")
    rl.apply()
    out = rl.revert()
    assert out["reverted"] >= 1
    assert _payload(rl, "h1") == before


def test_revert_is_safe_when_nothing_was_relabelled(rl):
    assert rl.revert()["reverted"] == 0


# --- status -------------------------------------------------------------------
def test_status_tracks_coverage_and_staleness(rl, head, monkeypatch):
    head("Dubstep")
    rl.apply()
    st = rl.status()
    assert st["relabelled"] == 2 and st["total"] == 3
    assert st["stale"] is False
    monkeypatch.setattr(rl, "_head_id", lambda: "custom:retrained")
    assert rl.status()["stale"] is True  # library labelled by an older head


# --- precedence ---------------------------------------------------------------
def test_relabel_outranks_salience_but_not_an_override():
    from vibenative.style import dominant_style

    base = {"salience": [{"style": "House", "score": 0.9}]}
    assert dominant_style(base) == "House"
    withrel = dict(base, relabel={"styles": [{"style": "Chillhop", "score": 0.8}]})
    assert dominant_style(withrel) == "Chillhop"
    assert dominant_style(dict(withrel, override="Trance")) == "Trance"


def test_keystone_follows_the_relabel_too():
    """The taxonomy must agree with the displayed genre, or the map and the
    label disagree about the same track."""
    from vibenative import keystone as K

    p = {
        "salience": [{"style": "Deep House", "score": 1.0}],
        "relabel": {"styles": [{"style": "Dubstep", "score": 1.0}]},
    }
    assert K.classify(p)["keystones"] == ["Dubstep"]
    assert K.classify({"salience": p["salience"]})["keystones"] == ["House"]


# --- the electronic-genre lexicon --------------------------------------------
def test_lexicon_resolves_genres_the_model_cannot_emit():
    """The classifier knows 400 Discogs styles; you type more than that. A name
    it can't emit must still find a keystone, not fall into non-electronic."""
    from vibenative import genrelex
    from vibenative import keystone as K

    if not genrelex.stats()["available"]:
        pytest.skip("genres_electronic.json is a local crawl artefact")
    for name, expected in [
        ("riddim", "Dubstep"),
        ("neurofunk", "Drum n Bass"),
        ("amapiano", "House"),
        ("melodic techno", "Techno"),
    ]:
        assert K.keystone_of(name) == expected


def test_an_alias_inherits_its_canonical_answer():
    """ "hard wave" is an alias of "hardwave", which is curated. Walking the
    alias's parents instead finds "wave" and lands somewhere else -- a curated
    answer for the same genre has to beat an inferred one."""
    from vibenative import genrelex
    from vibenative import keystone as K

    if not genrelex.stats()["available"]:
        pytest.skip("genres_electronic.json is a local crawl artefact")
    assert K.keystone_of("hard wave") == K.keystone_of("hardwave")


def test_curated_tables_outrank_the_lexicon():
    from vibenative import keystone as K

    assert K.keystone_of("Trap Wave") == "Dubstep"  # explicit, measured
    assert K.keystone_of("Deep House") == "House"
    assert K.keystone_of("Non-Music---Dialogue") is None


def test_missing_lexicon_degrades_quietly(monkeypatch, tmp_path):
    from vibenative import genrelex
    from vibenative import keystone as K

    monkeypatch.setattr(genrelex, "_index", None)
    monkeypatch.setattr(genrelex, "DATA", tmp_path / "absent.json")
    assert genrelex.get("riddim") is None
    assert genrelex.describe("riddim") is None
    assert genrelex.stats()["available"] is False
    assert K.keystone_of("Deep House") == "House"  # tables still work


def test_describe_filters_out_useless_stub_descriptions(monkeypatch):
    """Wikidata often says just "music genre" -- worse than nothing, because it
    looks like information."""
    from vibenative import genrelex

    monkeypatch.setattr(
        genrelex,
        "_index",
        {
            "stub": {"name": "stub", "description": "music genre"},
            "real": {"name": "real", "description": "a properly written description here"},
            "wiki": {"name": "wiki", "description": "music genre", "excerpt": "Long prose."},
        },
    )
    assert genrelex.describe("stub") is None
    assert genrelex.describe("real")
    assert genrelex.describe("wiki") == "Long prose."


def test_lexicon_lookup_cannot_recurse_forever(monkeypatch):
    """A cycle in the source data must be a miss, not a hang."""
    from vibenative import genrelex

    monkeypatch.setattr(
        genrelex,
        "_index",
        {
            "a": {"name": "a", "parents": ["b"]},
            "b": {"name": "b", "parents": ["a"]},
        },
    )
    assert genrelex.resolve_keystone("a", lambda _n: None) is None


# --- concurrent writes ----------------------------------------------------------
def test_an_override_made_during_apply_survives(client, monkeypatch):
    """apply() reads every payload, then spends a while on inference. An /override
    (or /weights) landing in that window used to be overwritten when apply wrote
    back the whole payload it had read. The inference is held on an event so the
    override lands exactly there; afterwards both must be in the payload."""
    import threading

    from vibenative import analysis, relabel
    from vibenative.repo.tracks import cache_put
    from vibenative.style import dominant_style

    hashes = [c * 40 for c in "abc"]
    for i, h in enumerate(hashes):
        payload = {"salience": [{"style": "House", "score": 0.9}], "bpm": 120 + i}
        cache_put(h, f"{h[:4]}.mp3", "", h[:4], payload, np.full(1280, i + 1, np.float32))

    inferring, release = threading.Event(), threading.Event()
    engine = fake_engine("Dubstep")
    classify = engine["classifier"]

    def held_classifier(v):
        inferring.set()
        assert release.wait(10), "test never released the classifier"
        return classify(v)

    engine["classifier"] = held_classifier
    monkeypatch.setattr(analysis, "get_engine", lambda: engine)

    result = {}
    worker = threading.Thread(target=lambda: result.update(relabel.apply()))
    worker.start()
    try:
        assert inferring.wait(10), "apply never reached inference"
        r = client.post(f"/override/{hashes[1]}", json={"genre": "Trance"})
        assert r.status_code == 200, r.get_json()
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert result["updated"] == 3

    conn = sqlite3.connect(current_db())
    try:
        rows = dict(conn.execute("SELECT hash, payload FROM tracks"))
        styles = dict(conn.execute("SELECT hash, style FROM tracks"))
    finally:
        conn.close()
    p = json.loads(rows[hashes[1]])
    assert p.get("override") == "Trance", "the override made during inference was lost"
    assert p["relabel"]["styles"][0]["style"] == "Dubstep"  # and the relabel landed too
    assert styles[hashes[1]] == "Trance" == dominant_style(p)
    for h in (hashes[0], hashes[2]):
        other = json.loads(rows[h])
        assert other["relabel"]["styles"][0]["style"] == "Dubstep"
        assert styles[h] == "Dubstep" == dominant_style(other)


def current_db():
    from vibenative.settings import current

    return current().db_path


def test_preview_reports_the_style_the_app_shows_as_from(client, monkeypatch):
    """A track with a weight adjustment reads as its adjusted style everywhere in
    the app; the preview's "from" must say the same, not the raw top."""
    from vibenative import analysis, relabel
    from vibenative.repo.tracks import cache_put
    from vibenative.style import dominant_style

    payload = {
        "salience": [{"style": "Techno", "score": 0.6}, {"style": "House", "score": 0.3}],
        "weights": {"House": 3},
    }
    assert dominant_style(payload) == "House"  # what the app shows
    cache_put("w" * 40, "w.mp3", "", "w", payload, np.ones(1280, np.float32))
    monkeypatch.setattr(analysis, "get_engine", lambda: fake_engine("Dubstep"))

    ex = {e["hash"]: e for e in relabel.preview()["examples"]}
    assert ex["w" * 40]["from"] == "House"
    assert ex["w" * 40]["to"] == "Dubstep"

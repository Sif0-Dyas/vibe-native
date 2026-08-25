"""Tests for retroactive re-labelling.

Runs against a scratch database with a stubbed classifier -- the point is the
bookkeeping (what gets written, what is preserved, what takes precedence), not
the model. A fake head lets a test say "now the head thinks everything is
Chillhop" and assert the library follows.
"""

import importlib
import json
import sqlite3

import numpy as np
import pytest

SCHEMA = """
CREATE TABLE tracks(hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
                    payload TEXT, embedding BLOB, created REAL);
"""

LABELS = ["Electronic---House", "Electronic---Techno", "Electronic---Dubstep"]


def _emb(seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal(1280).astype(np.float32).tobytes()


@pytest.fixture
def rl(tmp_path, monkeypatch):
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

    monkeypatch.setenv("GENRE_DB", str(dbfile))
    from vibenative import db as dbmod

    importlib.reload(dbmod)
    from vibenative import relabel

    monkeypatch.setattr(relabel, "db", dbmod.db)
    monkeypatch.setattr(relabel, "_db_lock", dbmod._db_lock)
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
    with sqlite3.connect(rl_mod.db.__globals__["DB_PATH"]) as c:
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
    from vibenative.routes._shared import _dominant_style

    base = {"salience": [{"style": "House", "score": 0.9}]}
    assert _dominant_style(base)[0] == "House"
    withrel = dict(base, relabel={"styles": [{"style": "Chillhop", "score": 0.8}]})
    assert _dominant_style(withrel)[0] == "Chillhop"
    assert _dominant_style(dict(withrel, override="Trance"))[0] == "Trance"


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

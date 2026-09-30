"""Blind labelling (/label, routes/labels.py, repo/labels.py, db v12) and the
label export (tools/export_labels.py).

The page exists to collect genres chosen without seeing the model's read, so the
tests that matter most are the blind ones: nothing the page's API returns carries
the read, and the page's script calls nothing else.
"""

import csv
import re
import sys
from pathlib import Path

import pytest

from vibenative.repo.tracks import cache_put

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import export_labels as ex  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LABEL_JS = ROOT / "src" / "vibenative" / "static" / "label.js"

# A style no vocabulary contains, so finding it in a response means the read leaked.
TELLTALE = "Zyzzyva Wave"


def _payload(**extra):
    return {
        "styles": [{"style": TELLTALE, "score": 0.9}, {"style": "House", "score": 0.1}],
        "salience": [{"style": TELLTALE, "score": 0.9}, {"style": "House", "score": 0.1}],
        "bpm": 173,
        "key": "F#",
        "scale": "minor",
        "tags": {"tag": {"title": "Song", "artist": "Artist"}},
    } | extra


@pytest.fixture(autouse=True)
def on_disk(monkeypatch):
    """Every recorded C:/music/ path exists, unless a test says otherwise."""
    real = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: p.as_posix().startswith("C:/music/") or real(p))


def _seed(h, filepath=None, title=None, **extra):
    cache_put(
        h,
        f"{h}.mp3",
        filepath if filepath is not None else f"C:/music/{h}.mp3",
        title or f"Title {h}",
        _payload(**extra),
        None,
    )
    return h


# --- the API ------------------------------------------------------------------


def test_next_serves_an_unlabelled_track_with_a_file(client):
    _seed("a" * 40)
    _seed("b" * 40, filepath="")  # browser-dropped: no file the page could play
    j = client.get("/api/v1/labels/next").get_json()
    assert j["track"]["hash"] == "a" * 40
    assert j["labelled"] == 0
    assert client.put(f"/api/v1/labels/{'a' * 40}", json={"genre": "Deep House"}).status_code == 200
    assert client.get("/api/v1/labels/next").get_json() == {"track": None, "labelled": 1}


def test_next_passes_over_tracks_whose_file_is_gone(client):
    _seed("a" * 40, filepath="D:/moved/away.mp3")
    _seed("b" * 40)
    for _ in range(5):
        assert client.get("/api/v1/labels/next").get_json()["track"]["hash"] == "b" * 40


def test_next_leaves_out_skipped_tracks(client):
    for h in ("a" * 40, "b" * 40, "c" * 40):
        _seed(h)
    skip = ",".join(("a" * 40, "c" * 40))
    for _ in range(5):
        assert (
            client.get(f"/api/v1/labels/next?skip={skip}").get_json()["track"]["hash"] == "b" * 40
        )


def test_put_replaces_and_delete_removes(client):
    h = _seed("a" * 40)
    client.put(f"/api/v1/labels/{h}", json={"genre": "  Deep   House "})
    j = client.put(f"/api/v1/labels/{h}", json={"genre": "Tech House"}).get_json()
    assert j == {"ok": True, "genre": "Tech House", "labelled": 1}
    recent = client.get("/api/v1/labels").get_json()
    assert [(r["hash"], r["genre"]) for r in recent["labels"]] == [(h, "Tech House")]
    assert client.delete(f"/api/v1/labels/{h}").get_json() == {"deleted": 1, "labelled": 0}
    assert client.get("/api/v1/labels").get_json()["labels"] == []


def test_put_whitespace_is_collapsed(client):
    h = _seed("a" * 40)
    assert (
        client.put(f"/api/v1/labels/{h}", json={"genre": "  Deep   House "}).get_json()["genre"]
        == "Deep House"
    )


@pytest.mark.parametrize("body", [{}, {"genre": "   "}, {"genre": "x" * 81}])
def test_put_refuses_a_missing_or_overlong_genre(client, body):
    h = _seed("a" * 40)
    assert client.put(f"/api/v1/labels/{h}", json=body).status_code == 400


def test_put_refuses_a_track_not_in_the_library(client):
    assert client.put(f"/api/v1/labels/{'z' * 40}", json={"genre": "House"}).status_code == 404


def test_a_label_is_not_an_override(client):
    """The label lives in its own table: the track's identity, and every view of
    it, is untouched -- and a later override doesn't touch the label."""
    h = _seed("a" * 40)
    client.put(f"/api/v1/labels/{h}", json={"genre": "Deep House"})
    assert "override" not in client.get(f"/api/v1/track/{h}").get_json()
    client.post(f"/api/v1/override/{h}", json={"genre": "Techno"})
    assert client.get("/api/v1/labels").get_json()["labels"][0]["genre"] == "Deep House"


def test_forgetting_a_track_forgets_its_label(client):
    h = _seed("a" * 40)
    client.put(f"/api/v1/labels/{h}", json={"genre": "Deep House"})
    client.delete(f"/api/v1/tracks/{h}")
    assert client.get("/api/v1/labels").get_json() == {"labelled": 0, "labels": []}


# --- blind --------------------------------------------------------------------


def test_no_labels_response_carries_the_read(client):
    h = _seed("a" * 40)
    bodies = [client.get("/api/v1/labels/next").get_data(as_text=True)]
    bodies.append(client.put(f"/api/v1/labels/{h}", json={"genre": "House"}).get_data(as_text=True))
    bodies.append(client.get("/api/v1/labels").get_data(as_text=True))
    bodies.append(client.get("/api/v1/labels/vocabulary").get_data(as_text=True))
    for body in bodies:
        assert TELLTALE not in body
        for field in ("style", "score", "bpm", "camelot", "salience", "dominant"):
            assert f'"{field}' not in body, (field, body)


def test_the_card_shows_only_who_and_what(client):
    _seed("a" * 40)
    assert set(client.get("/api/v1/labels/next").get_json()["track"]) == {"hash", "title", "artist"}


def test_the_vocabulary_is_not_the_librarys_reads(client):
    """Keystones (and the model's 400 styles when the label file is there), never
    the styles this library was read as."""
    _seed("a" * 40)
    names = client.get("/api/v1/labels/vocabulary").get_json()
    assert {"House", "Techno", "Drum n Bass"} <= set(names)
    assert TELLTALE not in names


def test_the_page_calls_only_the_labels_api_and_audio():
    js = re.sub(r"/\*.*?\*/|//[^\n]*", "", LABEL_JS.read_text(encoding="utf-8"), flags=re.S)
    assert "import " not in js  # nothing from the Analyzer comes along
    # One fetch, in getJSON; every URL is built from API, and names labels or audio.
    assert js.count("fetch(") == 1
    assert js.count("'/api/v1'") == 1 and js.count("/api/") == 1
    assert set(re.findall(r"\$\{API\}/([\w-]+)", js)) == {"labels", "audio"}


def test_the_label_page_is_served(client):
    page = client.get("/label")
    assert page.status_code == 200
    assert b'<script type="module" src="/static/label.js"></script>' in page.data
    assert b"Vibe Identify" in page.data
    assert client.get("/static/label.js").status_code == 200


# --- the export ----------------------------------------------------------------

LABELS = [
    "Electronic---Drum n Bass",
    "Electronic---Deep House",
    "Electronic---Tech House",
    "Electronic---Psy-Trance",
    "Electronic---Techno",
    "Electronic---Trance",
    "Hip Hop---Trap",
    "Pop---Ballad",
    "Rock---Punk",
]


@pytest.fixture()
def norm():
    return ex.Normaliser(LABELS)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("deep house", ("Deep House", "style")),
        ("Drum & Bass", ("Drum n Bass", "style")),
        ("Drum and Bass", ("Drum n Bass", "style")),
        ("drum'n'bass", ("Drum n Bass", "style")),
        ("psy trance", ("Psy-Trance", "style")),
        ("Techno (Peak Time / Driving)", ("Techno", "style")),
        ("Minimal / Deep House", ("Deep House", "style")),
        ("Hip-Hop", ("Hip Hop", "parent")),
        ("pop", ("Pop", "parent")),
        ("Trap Wave", ("Trap Wave", "other")),  # respelled, never collapsed to Dubstep
        ("Phonk", ("Phonk", "other")),
        ("Electronic", (None, "umbrella")),
        ("\ufffdlectronique", (None, "umbrella")),
        ("35", (None, None)),
        ("(17)", (None, None)),
        ("", (None, None)),
    ],
)
def test_normaliser_one(norm, raw, expected):
    assert norm.one(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Trance; Electronic", ("Trance", "style")),
        ("Electronic, Dance", (None, "umbrella")),
        ("House, Deep House, Tech House", (None, "ambiguous")),
        ("Deep House; deep house", ("Deep House", "style")),
        ("Phonk; Electronic", ("Phonk", "other")),
        ("Tech House", ("Tech House", "style")),
    ],
)
def test_normaliser_tag(norm, raw, expected):
    assert norm.tag(raw) == expected


def test_other_names_keep_the_first_spelling(norm):
    assert norm.one("Trap Wave") == ("Trap Wave", "other")
    assert norm.one("trap  wave") == ("Trap Wave", "other")


def test_export_reads_every_source(client, settings, tmp_path, norm):
    tagged = {"tags": {"tag": {"genre": "Drum & Bass"}}}
    _seed("o" * 40, override="deep house", **tagged)
    _seed("w" * 40, weights={"House": 3, TELLTALE: -3})  # House is now the top
    _seed("m" * 40, tags={"tag": {"genre": "Electronic"}})
    _seed("n" * 40, override="Techno", weights={"House": 3, TELLTALE: -3})
    client.put(f"/api/v1/labels/{'m' * 40}", json={"genre": "Tech House"})

    rows, stats = ex.collect(settings.db_path, norm=norm)
    got = {(h[0], g, s) for h, _, g, s in rows}
    assert got == {
        ("o", "Deep House", "override"),
        ("o", "Drum n Bass", "id3-genre"),
        ("w", "House", "weight"),
        ("n", "Techno", "override"),
        ("n", "House", "weight"),  # the override does not hide the adjustments
        ("m", "Tech House", "manual"),
    }
    assert all(fp == f"C:/music/{h}.mp3" for h, fp, _, _ in rows)
    assert stats["rows"] == {"override": 2, "weight": 2, "id3-genre": 1, "manual": 1}
    assert stats["kinds"]["id3-genre"] == {"style": 1, "umbrella": 1}

    out = tmp_path / "labels.csv"
    ex.write_csv(rows, out)
    with open(out, newline="", encoding="utf-8") as f:
        table = list(csv.reader(f))
    assert table[0] == ["hash", "filepath", "genre", "source"]
    assert [r[3] for r in table[1:]] == sorted((r[3] for r in table[1:]), key=ex.SOURCES.index)
    assert "tracks" in ex.report(stats)


def test_export_does_not_write_the_database(client, settings, norm):
    """Read-only: a database from before v12 is read as it is, not migrated."""
    import sqlite3

    _seed("o" * 40, override="Techno")
    conn = sqlite3.connect(settings.db_path)
    conn.execute("DROP TABLE genre_labels")
    conn.execute("UPDATE schema_version SET version = 11")
    conn.commit()
    conn.close()
    rows, stats = ex.collect(settings.db_path, norm=norm)
    assert [(g, s) for _, _, g, s in rows] == [("Techno", "override")]
    conn = sqlite3.connect(settings.db_path)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 11
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()
    assert "genre_labels" not in tables

"""One sanitizer for user-typed names (vibenative.names.safe_name), and the
stricter rule for genre folders (names.genre_folder).

safe_name replaced nine copies of the same expression. The table below was
captured from those copies BEFORE they were replaced -- for each name, what the
genre folder sites (routes/library, routes/training), the Rekordbox export's
file name, snapshots._safe and trainsets._safe (now names.genre_folder)
produced -- so every rule is held to the exact output it had.

Since then the genre routes use genre_folder: a name with no letter or digit
("///", "...") gets a 400 before anything is copied or written. safe_name
itself still gives such a name its old folder name ("___").
"""

import io

import pytest

from vibenative import snapshots
from vibenative.names import GENRE_NEEDS_ALNUM, genre_folder, safe_name

# (name, safe_name folder, playlist file name, snapshot label, genre_folder)
BEFORE = [
    ("House", "House", "House", "House", "House"),
    ("Drum n Bass", "Drum n Bass", "Drum n Bass", "Drum-n-Bass", "Drum n Bass"),
    ("  Deep House  ", "Deep House", "Deep House", "Deep-House", "Deep House"),
    ("AC/DC", "AC_DC", "AC_DC", "AC_DC", "AC_DC"),
    ("Hip-Hop/R&B", "Hip-Hop_R_B", "Hip-Hop_R_B", "Hip-Hop_R_B", "Hip-Hop_R_B"),
    ("St. Germain", "St_ Germain", "St_ Germain", "St_-Germain", "St_ Germain"),
    ("Dubstep.", "Dubstep_", "Dubstep_", "Dubstep_", "Dubstep_"),
    ("Café del Mar", "Café del Mar", "Café del Mar", "Café-del-Mar", "Café del Mar"),
    ("Ünïcödé Ñame", "Ünïcödé Ñame", "Ünïcödé Ñame", "Ünïcödé-Ñame", "Ünïcödé Ñame"),
    ("東京 Techno", "東京 Techno", "東京 Techno", "東京-Techno", "東京 Techno"),
    ("Trap 🔥", "Trap _", "Trap _", "Trap-_", "Trap _"),
    ("///", "___", "___", "___", None),
    ("...", "___", "___", "___", None),
    ("", "", "playlist", "snapshot", None),
    ("   ", "", "playlist", "snapshot", None),
    ("a_b-c d", "a_b-c d", "a_b-c d", "a_b-c-d", "a_b-c d"),
    (
        "C:\\evil\\..\\path",
        "C__evil____path",
        "C__evil____path",
        "C__evil____path",
        "C__evil____path",
    ),
    ("../../etc", "______etc", "______etc", "______etc", "______etc"),
    (
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    ),
]


@pytest.mark.parametrize("name, folder, playlist, snapshot, trainset", BEFORE)
def test_every_rule_gives_what_it_gave_before(name, folder, playlist, snapshot, trainset):
    assert safe_name(name) == folder
    assert snapshots._safe(name) == snapshot
    assert genre_folder(name) == trainset  # was trainsets._safe: same values


@pytest.mark.parametrize("name, folder, playlist, snapshot, trainset", BEFORE)
def test_save_training_files_into_the_same_folder(
    client, tmp_path, monkeypatch, name, folder, playlist, snapshot, trainset
):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    r = client.post(
        "/save_training",
        data={"genre": name, "file": (io.BytesIO(b"RIFF"), "t.wav")},
        content_type="multipart/form-data",
    )
    if not name.strip():
        assert r.status_code == 400  # "genre required", before any sanitising
        assert r.get_json() == {"error": "genre required"}
    elif trainset is None:  # no letter or digit: refused, nothing filed
        assert r.status_code == 400
        assert r.get_json() == {"error": GENRE_NEEDS_ALNUM}
        assert not (tmp_path / "genre_training").exists()
    else:
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["genre"] == folder
        assert (tmp_path / "genre_training" / folder / "t.wav").is_file()


@pytest.mark.parametrize("name, folder, playlist, snapshot, trainset", BEFORE)
def test_rekordbox_export_names_the_file_the_same(
    client, name, folder, playlist, snapshot, trainset
):
    from vibenative.repo import playlists as playlists_repo

    pid = playlists_repo.save(name, [])
    r = client.get(f"/playlists/{pid}/rekordbox")
    assert r.status_code == 200
    assert r.headers["Content-Disposition"] == f'attachment; filename="{playlist}.xml"'


def test_the_expression_lives_in_one_place():
    from pathlib import Path

    pkg = Path(__file__).resolve().parent.parent / "src" / "vibenative"
    hits = [
        p.relative_to(pkg).as_posix()
        for p in pkg.rglob("*.py")
        if "isalnum() or " in p.read_text(encoding="utf-8") and p.name != "names.py"
    ]
    assert hits == []


# --- every genre -> folder route refuses a name with no letter or digit ---------
NO_ALNUM = ["///", "...", "- _ -", "🔥🔥"]


def _track_with_file(tmp_path):
    """A library track whose audio is on disk, so a route would copy it."""
    from vibenative.repo.tracks import cache_put

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    h = "a" * 40
    cache_put(h, "song.wav", str(audio), "song", {"styles": [], "duration": 100.0}, None)
    return h


@pytest.mark.parametrize("genre", NO_ALNUM)
def test_override_refuses_before_writing_or_copying(client, tmp_path, settings, genre):
    from vibenative.repo.tracks import payload

    h = _track_with_file(tmp_path)
    r = client.post(f"/override/{h}", json={"genre": genre})
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    assert "override" not in payload(h)  # nothing written
    assert not settings.training_root.exists()  # nothing copied


@pytest.mark.parametrize("genre", NO_ALNUM)
def test_segment_override_refuses_before_writing(client, tmp_path, settings, genre):
    from vibenative.repo.tracks import segment_overrides

    h = _track_with_file(tmp_path)
    r = client.post("/override_segment", json={"hash": h, "genre": genre, "start": 0, "end": 5})
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    assert segment_overrides(h) == []
    assert not settings.training_root.exists()


@pytest.mark.parametrize("genre", NO_ALNUM)
def test_training_confirm_refuses_before_labelling(client, tmp_path, settings, genre):
    from vibenative.repo.training import label_hashes

    h = _track_with_file(tmp_path)
    r = client.post("/training/confirm", json={"hash": h, "genre": genre})
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    assert label_hashes(genre) == set()
    assert not settings.training_root.exists()


@pytest.mark.parametrize("genre", ["...", "- _ -", "🔥🔥"])  # no "/" in a URL segment
def test_training_set_routes_refuse(client, tmp_path, settings, genre):
    from urllib.parse import quote

    from vibenative.repo.training import labels_any_case

    h = _track_with_file(tmp_path)
    g = quote(genre, safe="")
    r = client.post(f"/training/set/{g}/add", json={"hashes": [h]})
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    assert labels_any_case(genre) == []
    r = client.get(f"/training/set/{g}/export")
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    r = client.post(f"/training/set/{g}/reset")
    assert (r.status_code, r.get_json()) == (400, {"error": GENRE_NEEDS_ALNUM})
    assert not settings.training_root.exists()


def test_a_name_with_a_letter_is_still_filed(client, tmp_path, settings):
    """The rule only refuses names with nothing usable in them."""
    h = _track_with_file(tmp_path)
    assert client.post(f"/override/{h}", json={"genre": "R&B / Soul"}).status_code == 200
    assert (settings.training_root / "R_B _ Soul" / "song.wav").is_file()

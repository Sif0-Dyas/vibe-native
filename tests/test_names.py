"""One sanitizer for user-typed names (vibenative.names.safe_name).

It replaced nine copies of the same expression. The table below was captured
from those copies BEFORE they were replaced -- for each name, what the genre
folder sites (routes/library, routes/training), the Rekordbox export's file
name, snapshots._safe and trainsets._safe produced -- so every call site is
held to the exact output it had.
"""

import io

import pytest

from vibenative import snapshots, trainsets
from vibenative.names import safe_name

# (name, genre folder, playlist file name, snapshot label, trainsets._safe)
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
    assert trainsets._safe(name) == trainset


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
    elif not folder:
        assert r.get_json() == {"error": "invalid genre name"}
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

"""Shared pytest fixtures.

Every test runs with FAKE_ANALYZER=1 (no Essentia / no model loads) and a
throwaway SQLite database, so the suite never touches real models or the
user's ~/genre_v2.db. Config is read at import time, so we set the env vars
first and reload the package per test for full isolation.
"""

import os
import sys
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolated_taxonomy(tmp_path, monkeypatch):
    """Point the taxonomy overlay at a scratch path for every test.

    The overlay changes how every genre resolves. Without this the suite would
    read whatever the developer has saved in the app -- so a run would pass or
    fail depending on whose machine it was on, and a genuine regression could
    hide behind someone's local edit.
    """
    monkeypatch.setenv("VIBE_TAXONOMY", str(tmp_path / "taxonomy.json"))


@pytest.fixture()
def client():
    os.environ["FAKE_ANALYZER"] = "1"
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["GENRE_DB"] = tmp.name

    for name in list(sys.modules):  # force a clean import per test
        if name == "vibenative" or name.startswith("vibenative."):
            del sys.modules[name]
    import vibenative

    app = vibenative.create_app()
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c

    os.unlink(tmp.name)

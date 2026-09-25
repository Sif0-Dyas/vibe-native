"""The app never serves anything without its token and a loopback Host.

Covers the whole surface: a page (/), an API route, a static file and an
unmatched URL -- the guard is app-level, so /static and 404s are behind it too.
"""

import pytest

from conftest import TEST_TOKEN

URLS = ["/", "/library", "/static/app.js", "/no-such-page"]


@pytest.fixture()
def anon(client):
    """A second client on the same app, with no cookie."""
    return client.application.test_client()


@pytest.mark.parametrize("url", URLS)
def test_no_token_is_403(anon, url):
    assert anon.get(url).status_code == 403


@pytest.mark.parametrize("url", URLS)
def test_wrong_token_is_403(anon, url):
    assert anon.get(url, query_string={"k": "not-the-token"}).status_code == 403
    anon.set_cookie("vibe_token", "not-the-token")
    assert anon.get(url).status_code == 403


def test_the_right_token_opens_everything(client):
    assert client.get("/").status_code == 200
    assert client.get("/library").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/no-such-page").status_code == 404  # past the guard, then not found


def test_k_on_the_first_load_sets_the_cookie_static_files_need(anon):
    # The real load order: /?k=<token> first, then the page's static assets with
    # nothing but the cookie that first response set.
    first = anon.get("/", query_string={"k": TEST_TOKEN})
    assert first.status_code == 200
    cookie = first.headers.get("Set-Cookie", "")
    assert "vibe_token=" + TEST_TOKEN in cookie and "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert anon.get("/static/app.js").status_code == 200
    assert anon.get("/library").status_code == 200


@pytest.mark.parametrize("url", ["/", "/library", "/static/app.js"])
def test_non_loopback_host_is_403_even_with_the_token(anon, url):
    # DNS rebinding: a page on evil.example resolves to 127.0.0.1 and the browser
    # sends Host: evil.example. The Host check runs unconditionally now.
    ok = anon.get(url, query_string={"k": TEST_TOKEN}, headers={"Host": "localhost"})
    assert ok.status_code == 200
    bad = anon.get(url, query_string={"k": TEST_TOKEN}, headers={"Host": "evil.example"})
    assert bad.status_code == 403
    bad = anon.get(url, query_string={"k": TEST_TOKEN}, headers={"Host": "evil.example:5005"})
    assert bad.status_code == 403


def test_dev_token_is_generated_once_and_reused(client, monkeypatch, tmp_path):
    # Restarting the dev server keeps an open tab signed in: with GENRE_TOKEN unset,
    # the first start writes <config_dir>/dev_token and later starts reuse it.
    import os
    import stat
    import sys

    import vibenative

    cfg = tmp_path / "fresh-config"
    monkeypatch.setenv("VIBE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("GENRE_TOKEN", raising=False)
    a, b = vibenative.create_app(), vibenative.create_app()
    token = a.config["AUTH_TOKEN"]
    assert len(token) >= 32 and b.config["AUTH_TOKEN"] == token
    saved = cfg / "dev_token"
    assert saved.read_text(encoding="ascii").strip() == token
    if sys.platform != "win32":  # Windows has no owner-only mode bits to check
        assert stat.S_IMODE(os.stat(saved).st_mode) == 0o600


def test_genre_token_overrides_the_saved_dev_token(client, monkeypatch, tmp_path):
    import vibenative

    monkeypatch.setenv("VIBE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("GENRE_TOKEN", raising=False)
    saved = vibenative.create_app().config["AUTH_TOKEN"]
    monkeypatch.setenv("GENRE_TOKEN", "pinned")
    assert vibenative.create_app().config["AUTH_TOKEN"] == "pinned"
    assert (tmp_path / "cfg" / "dev_token").read_text(encoding="ascii").strip() == saved


def test_a_packaged_build_never_writes_a_dev_token(client, monkeypatch, tmp_path):
    import sys

    import vibenative

    cfg = tmp_path / "frozen-config"
    monkeypatch.setenv("VIBE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("GENRE_TOKEN", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    a, b = vibenative.create_app(), vibenative.create_app()
    assert a.config["AUTH_TOKEN"] != b.config["AUTH_TOKEN"]  # fresh each start
    assert not (cfg / "dev_token").exists()


def test_main_prints_the_url_with_the_token_once(client, monkeypatch, capsys):
    import flask

    import vibenative.__main__ as entry

    monkeypatch.setenv("GENRE_PORT", "5123")
    monkeypatch.setattr(flask.Flask, "run", lambda self, **kw: None)
    entry.main()
    out = capsys.readouterr().out
    assert out.count("?k=") == 1
    assert f"http://127.0.0.1:5123/?k={TEST_TOKEN}" in out


@pytest.mark.parametrize(
    "site, status",
    [
        ("cross-site", 403),
        ("same-site", 403),  # another localhost port is another origin
        ("same-origin", 200),
        ("none", 200),
        (None, 200),  # no header: not a browser fetch; the token alone decides
    ],
)
def test_writes_from_another_site_are_refused(client, site, status):
    headers = {"Sec-Fetch-Site": site} if site else {}
    r = client.post("/vibes", json={"name": f"v-{site}"}, headers=headers)
    assert r.status_code == status


def test_reads_are_not_subject_to_the_fetch_site_check(client):
    # Only writes are refused; a cross-site GET still needs the token like any other.
    assert client.get("/library", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200

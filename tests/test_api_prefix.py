"""Every API route lives under /api/v1; only the page and its static files are
at the root. There are no compatibility aliases -- the old paths are gone."""

from vibenative.routes import API_PREFIX


def test_every_route_but_the_page_is_under_the_api_prefix(client):
    rules = {r.rule for r in client.application.url_map.iter_rules()}
    at_root = {r for r in rules if not r.startswith(API_PREFIX + "/")}
    assert at_root == {"/", "/static/<path:filename>"}
    assert API_PREFIX == "/api/v1"


def test_the_old_unprefixed_paths_are_gone(client):
    for path in ("/status", "/library", "/map", "/vibes", "/tags"):
        assert client.get(path).status_code == 404, path
    assert client.get("/api/v1/status").status_code == 200


def test_the_auth_guard_covers_the_prefixed_api(client):
    anon = client.application.test_client()
    assert anon.get("/api/v1/library").status_code == 403
    cross = {"Sec-Fetch-Site": "cross-site"}
    assert client.post("/api/v1/tags", json={"name": "x"}, headers=cross).status_code == 403


def test_deletes_are_delete_verbs_and_the_post_forms_are_gone(client):
    """A delete is DELETE on the resource; the old POST-for-delete paths are gone."""
    for path, body in (
        ("/api/v1/playlists/1/delete", None),
        ("/api/v1/forget/" + "a" * 40, None),
        ("/api/v1/override_segment/delete", {"id": 1}),
        ("/api/v1/vibes/remove", {"vibe_id": 1, "hash": "a"}),
        ("/api/v1/vibes/clear", {"vibe_id": 1}),
        ("/api/v1/vibes/delete", {"vibe_id": 1}),
    ):
        assert client.post(path, json=body).status_code in (404, 405), path
    deletes = {
        r.rule for r in client.application.url_map.iter_rules() if "DELETE" in (r.methods or ())
    }
    assert deletes == {
        "/api/v1/playlists/<int:pid>",
        "/api/v1/tracks/<h>",
        "/api/v1/override_segment/<int:oid>",
        "/api/v1/vibes/<int:vid>",
        "/api/v1/vibes/<int:vid>/tracks",
        "/api/v1/vibes/<int:vid>/tracks/<h>",
    }
    cross = {"Sec-Fetch-Site": "cross-site"}
    assert client.delete("/api/v1/vibes/1", headers=cross).status_code == 403

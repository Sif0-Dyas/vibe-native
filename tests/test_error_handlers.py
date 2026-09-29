"""The blueprint's error handlers: an UploadError answers with its own status and
message, anything unexpected is logged with its traceback and answers 500
{"error": "internal error"} -- and HTTP errors (413, 405...) pass through as
themselves rather than becoming 500s.

Written against the per-route try/excepts before they were folded into the
handlers, so each case here is the behaviour those routes already had.
"""

import io
import logging

import pytest


def _upload(name, data=b"RIFF0000WAVE"):
    return {"file": (io.BytesIO(data), name)}


@pytest.mark.parametrize("route", ["/analyze", "/refine"])
def test_no_file_is_400(client, route):
    r = client.post(route, data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert set(r.get_json()) == {"error"}


@pytest.mark.parametrize("route", ["/analyze", "/refine"])
def test_wrong_type_is_415_with_the_suffix(client, route):
    r = client.post(route, data=_upload("notes.txt"), content_type="multipart/form-data")
    assert r.status_code == 415
    assert r.get_json() == {"error": "unsupported file type: .txt"}


def test_save_training_upload_errors_keep_their_status(client):
    r = client.post("/save_training", data={"genre": "House"}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert r.get_json() == {"error": "no file or filepath provided"}
    r = client.post(
        "/save_training",
        data={"genre": "House", **_upload("x.exe")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 415
    assert r.get_json() == {"error": "unsupported file type: .exe"}


@pytest.mark.parametrize("route", ["/analyze", "/refine"])
def test_an_unexpected_failure_is_500_internal_error_and_logged(client, monkeypatch, caplog, route):
    from vibenative.routes import analysis as A

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(A, "saved_upload", boom)
    with caplog.at_level(logging.ERROR, logger="vibenative"):
        r = client.post(route, data=_upload("a.wav"), content_type="multipart/form-data")
    assert r.status_code == 500
    assert r.get_json() == {"error": "internal error"}
    assert "kaboom" not in r.get_data(as_text=True)  # no internals in the response
    assert any(rec.exc_info and "kaboom" in str(rec.exc_info[1]) for rec in caplog.records)


def test_an_http_error_is_not_turned_into_a_500(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 10
    r = client.post(
        "/analyze", data=_upload("a.wav", b"x" * 100), content_type="multipart/form-data"
    )
    assert r.status_code == 413
    assert client.get("/analyze").status_code == 405  # POST-only route

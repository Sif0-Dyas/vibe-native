"""Discogs credentials travel only in the Authorization header, and never reach a log.

urlopen is replaced, so nothing here touches the network.
"""

import io
import logging
import urllib.error

import pytest

from vibenative import lookup

TOKEN = "tok-SECRET-123"  # nosec B105  # a fake credential for the test
KEY, SECRET = "key-SECRET-456", "sec-SECRET-789"  # nosec B105


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def sent(monkeypatch):
    """Every Request lookup sends, captured; answers with an empty result."""
    reqs = []

    def fake_urlopen(req, timeout=None):
        reqs.append(req)
        return _Resp(b'{"results": []}')

    monkeypatch.setattr(lookup.urllib.request, "urlopen", fake_urlopen)
    return reqs


def _creds(monkeypatch, token="", key="", secret=""):
    monkeypatch.setattr(lookup, "DISCOGS_TOKEN", token)
    monkeypatch.setattr(lookup, "DISCOGS_KEY", key)
    monkeypatch.setattr(lookup, "DISCOGS_SECRET", secret)


@pytest.mark.parametrize(
    "creds, header, values",
    [
        ({"token": TOKEN}, f"Discogs token={TOKEN}", [TOKEN]),
        ({"key": KEY, "secret": SECRET}, f"Discogs key={KEY}, secret={SECRET}", [KEY, SECRET]),
    ],
    ids=["personal-token", "consumer-key-secret"],
)
def test_credentials_go_in_the_authorization_header_only(monkeypatch, sent, creds, header, values):
    _creds(monkeypatch, **creds)
    data, err = lookup.fetch_discogs("Skrillex", "Rumble")
    assert err is None and data == {"results": []}
    (req,) = sent
    assert req.get_header("Authorization") == header
    assert req.get_header("User-agent") == lookup.USER_AGENT  # Discogs requires an identifying UA
    for v in values:
        assert v not in req.full_url
    for name in ("token=", "key=", "secret="):
        assert name not in req.full_url


def test_a_personal_token_wins_over_a_key_pair(monkeypatch, sent):
    _creds(monkeypatch, token=TOKEN, key=KEY, secret=SECRET)
    lookup.fetch_discogs("a", "b")
    assert sent[0].get_header("Authorization") == f"Discogs token={TOKEN}"


def test_unconfigured_sends_nothing(monkeypatch, sent):
    _creds(monkeypatch)
    data, err = lookup.fetch_discogs("a", "b")
    assert data is None and "DISCOGS_TOKEN" in err
    assert sent == []


@pytest.mark.parametrize(
    "boom",
    [
        lambda req: urllib.error.HTTPError(req.full_url, 401, "Unauthorized", req.headers, None),
        # an exception whose message quotes the whole request, as some do
        lambda req: ValueError(f"bad request {req.full_url} {req.headers}"),
    ],
    ids=["http-401", "exception-quoting-the-request"],
)
@pytest.mark.parametrize(
    "creds", [{"token": TOKEN}, {"key": KEY, "secret": SECRET}], ids=["token", "key-secret"]
)
def test_a_failed_request_logs_host_and_status_but_no_credential(monkeypatch, caplog, creds, boom):
    _creds(monkeypatch, **creds)

    def failing_urlopen(req, timeout=None):
        raise boom(req)

    monkeypatch.setattr(lookup.urllib.request, "urlopen", failing_urlopen)
    with caplog.at_level(logging.DEBUG):
        data, err = lookup.fetch_discogs("Skrillex", "Rumble")
    assert data is None and err
    assert "host=api.discogs.com" in caplog.text
    for v in creds.values():
        assert v not in caplog.text
    assert "Authorization" not in caplog.text and "database/search" not in caplog.text

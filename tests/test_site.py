import os

# Make sure demo mode is off for the tests, whatever your shell has set.
os.environ.pop("DEMO_FAKE_WALLET", None)

import pytest
import requests

import app as site


class FakeResponse:
    """Stands in for the verifier's answer, so tests don't need Docker."""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


@pytest.fixture
def client():
    site.app.config["TESTING"] = True
    return site.app.test_client()


def give_pass(client):
    with client.session_transaction() as s:
        s["is_adult"] = True


def test_home_page_loads(client):
    assert client.get("/").status_code == 200


def test_members_blocks_visitors_without_a_pass(client):
    r = client.get("/members")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")


def test_members_opens_with_a_pass(client):
    give_pass(client)
    r = client.get("/members")
    assert r.status_code == 200
    assert b"Members area" in r.data


def test_logout_removes_the_pass(client):
    give_pass(client)
    client.get("/logout")
    assert client.get("/members").status_code == 302


def test_demo_route_is_off_by_default(client):
    assert client.get("/demo-verify").status_code == 404


def test_health_reports_verifier_down(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.ConnectionError("no verifier")

    monkeypatch.setattr(site.requests, "get", refuse)
    r = client.get("/health")
    assert r.status_code == 503
    assert b"down" in r.data


def test_failed_verdict_does_not_grant_access(client, monkeypatch):
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    monkeypatch.setattr(
        site.requests, "post",
        lambda *a, **k: FakeResponse({"state": "failed", "reason": "proof-invalid"}),
    )
    r = client.post("/api/finish", json={"response": "x"})
    assert r.get_json()["ok"] is False
    assert client.get("/members").status_code == 302


def test_verified_verdict_grants_access(client, monkeypatch):
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    monkeypatch.setattr(
        site.requests, "post",
        lambda *a, **k: FakeResponse({"state": "verified", "result": {"age_over_18": True}}),
    )
    r = client.post("/api/finish", json={"response": "x"})
    assert r.get_json()["ok"] is True
    assert client.get("/members").status_code == 200


def test_verifier_url_comes_from_environment(monkeypatch):
    import importlib

    monkeypatch.setenv("VERIFIER_URL", "http://example.test:1234")
    reloaded = importlib.reload(site)
    assert reloaded.VERIFIER == "http://example.test:1234"

    monkeypatch.delenv("VERIFIER_URL")
    importlib.reload(site)
    assert site.VERIFIER == "http://127.0.0.1:8000"

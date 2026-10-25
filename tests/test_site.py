import os

# Make sure demo mode is off for the tests, whatever your shell has set.
os.environ.pop("DEMO_FAKE_WALLET", None)

import pytest
import requests

import agecheck
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

    monkeypatch.setattr(agecheck.requests, "get", refuse)
    r = client.get("/health")
    assert r.status_code == 503
    assert b"down" in r.data


def test_failed_verdict_does_not_grant_access(client, monkeypatch):
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    monkeypatch.setattr(
        agecheck.requests, "post",
        lambda *a, **k: FakeResponse({"state": "failed", "reason": "proof-invalid"}),
    )
    r = client.post("/api/finish", json={"response": "x"})
    assert r.get_json()["ok"] is False
    assert client.get("/members").status_code == 302


def test_verified_verdict_grants_access(client, monkeypatch):
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    monkeypatch.setattr(
        agecheck.requests, "post",
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


# ---- Demo mode tests: the verifier and the fake wallet are both pretend here ----

def fake_wallet_setup(monkeypatch, verdict, wallet_returncode=0, wallet_stderr=""):
    """Turn demo mode on and replace the verifier and the docker call with fakes."""
    import json
    from types import SimpleNamespace

    calls = {}

    def fake_post(url, **kwargs):
        if url.endswith("/sessions"):
            return FakeResponse({"session_id": "s1", "transports": {"dc": {"digital": "offer"}}})
        calls["presentation_body"] = kwargs.get("json")
        return FakeResponse(verdict)

    def fake_run(cmd, **kwargs):
        calls["wallet_input"] = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=wallet_returncode,
            stdout=json.dumps({"response": "abc"}),
            stderr=wallet_stderr,
        )

    monkeypatch.setattr(site, "DEMO", True)
    monkeypatch.setattr(agecheck.requests, "post", fake_post)
    monkeypatch.setattr(site.subprocess, "run", fake_run)
    return calls


def test_demo_verified_grants_access(client, monkeypatch):
    calls = fake_wallet_setup(monkeypatch, {"state": "verified", "result": {"age_over_18": True}})
    r = client.get("/demo-verify")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/members")
    assert client.get("/members").status_code == 200
    # The wallet got the verifier's offer and this site's origin, and the
    # wallet's answer went to the verifier untouched.
    assert calls["wallet_input"]["request"] == {"digital": "offer"}
    assert calls["wallet_input"]["origin"] == site.SITE_ORIGIN
    assert calls["presentation_body"] == {"response": "abc"}


def test_demo_failed_verdict_denies(client, monkeypatch):
    fake_wallet_setup(monkeypatch, {"state": "failed", "reason": "untrusted-issuer"})
    r = client.get("/demo-verify")
    assert r.status_code == 403
    assert b"untrusted-issuer" in r.data
    assert client.get("/members").status_code == 302


def test_demo_verified_but_not_over_18_denies(client, monkeypatch):
    fake_wallet_setup(monkeypatch, {"state": "verified", "result": {"age_over_18": False}})
    r = client.get("/demo-verify")
    assert r.status_code == 403
    assert client.get("/members").status_code == 302


def test_demo_wallet_crash_shows_escaped_error(client, monkeypatch):
    fake_wallet_setup(monkeypatch, {}, wallet_returncode=1, wallet_stderr="<b>boom</b>")
    r = client.get("/demo-verify")
    assert r.status_code == 500
    assert b"Fake wallet failed" in r.data
    assert b"&lt;b&gt;boom" in r.data
    assert b"<b>boom</b>" not in r.data
    assert client.get("/members").status_code == 302


def test_demo_link_only_shown_when_demo_is_on(client, monkeypatch):
    assert b"demo-verify" not in client.get("/verify").data
    monkeypatch.setattr(site, "DEMO", True)
    assert b"demo-verify" in client.get("/verify").data

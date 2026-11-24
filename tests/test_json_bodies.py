"""Finish steps answer a body that is valid JSON but not an object, instead of crashing."""

import pytest

import app as site
from tests.test_flask_gate import make_site as make_age_site
from tests.test_flask_passport import make_site as make_passport_site
from tests.test_passport import open_page

NOT_OBJECTS = ["[1]", '"text"', "5", "null", "{not json"]


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_site_age_finish(monkeypatch, body):
    seen = []

    class Verifier:
        def finish(self, sid, response):
            seen.append(response)
            return False, {"reason": "bad response"}

    monkeypatch.setattr(site, "verifier", Verifier())
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["av_session"] = "s1"
    reply = client.post("/api/finish", data=body, content_type="application/json")
    assert reply.status_code < 500
    assert reply.get_json()["ok"] is False
    assert seen == [None]


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_site_passport_finish(monkeypatch, body):
    seen = []

    def check(proofs, result, domain, scope):
        seen.append((proofs, result))
        return False

    monkeypatch.setattr(site, "PASSPORT_URL", "http://passport:8100")
    monkeypatch.setattr(site, "_passport_client", {})
    monkeypatch.setattr(site, "passport_check", check)
    client = site.app.test_client()
    open_page(client)
    reply = client.post("/api/passport/finish", data=body, content_type="application/json")
    assert reply.status_code < 500
    assert reply.get_json()["ok"] is False
    assert seen == [(None, None)]


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_age_gate_finish(body):
    client = make_age_site()[0].test_client()
    client.post("/age/start")
    reply = client.post("/age/finish", data=body, content_type="application/json")
    assert reply.status_code < 500


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_passport_gate_finish(body):
    client = make_passport_site()[0].test_client()
    client.post("/passport-check/start")
    reply = client.post("/passport-check/finish", data=body, content_type="application/json")
    assert reply.status_code < 500

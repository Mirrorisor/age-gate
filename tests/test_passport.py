"""The optional passport route: page, client script proxy, and the finish step."""

import pytest
import requests

import app as site


@pytest.fixture
def passport_on(monkeypatch):
    monkeypatch.setattr(site, "PASSPORT_URL", "http://passport:8100")
    monkeypatch.setattr(site, "_passport_client", {})


def open_page(client):
    """Visit /passport like a browser; returns the scope the page and the session now share."""
    page = client.get("/passport").get_data(as_text=True)
    scope = page.split('data-scope="')[1].split('"')[0]
    with client.session_transaction() as s:
        assert s["passport_scope"] == scope
    return scope


def test_everything_is_off_without_a_passport_service(monkeypatch):
    monkeypatch.setattr(site, "PASSPORT_URL", "")
    client = site.app.test_client()
    assert client.get("/passport").status_code == 404
    assert client.get("/passport/client.js").status_code == 404
    assert client.post("/api/passport/finish", json={}).status_code == 404
    assert "/passport" not in client.get("/verify").get_data(as_text=True)


def test_the_verify_page_offers_the_passport_when_it_is_on(passport_on):
    assert 'href="/passport"' in site.app.test_client().get("/verify").get_data(as_text=True)


def test_the_page_carries_the_nonce_and_only_it_may_open_websockets(passport_on):
    client = site.app.test_client()
    response = client.get("/passport")
    page = response.get_data(as_text=True)
    policy = response.headers["Content-Security-Policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert f'<script type="module" nonce="{nonce}" src="/passport/client.js"' in page
    assert "connect-src 'self' wss:;" in policy
    assert "connect-src 'self';" in client.get("/verify").headers["Content-Security-Policy"]


def test_a_good_proof_sets_the_pass_and_sends_the_site_domain(passport_on, monkeypatch):
    seen = {}

    def check(proofs, result, domain, scope):
        seen.update(proofs=proofs, result=result, domain=domain, scope=scope)
        return True

    monkeypatch.setattr(site, "passport_check", check)
    monkeypatch.setattr(site, "SITE_ORIGIN", "https://some-words.trycloudflare.com")
    client = site.app.test_client()
    scope = open_page(client)
    reply = client.post("/api/passport/finish", json={"proofs": ["p"], "result": {"age": 1}})
    assert reply.get_json() == {"ok": True, "next": "/members"}
    assert seen == {
        "proofs": ["p"],
        "result": {"age": 1},
        "domain": "some-words.trycloudflare.com",
        "scope": scope,
    }
    with client.session_transaction() as s:
        assert s["is_adult"] is True


def test_a_refused_proof_does_not_pass(passport_on, monkeypatch):
    monkeypatch.setattr(site, "passport_check", lambda *_: False)
    client = site.app.test_client()
    open_page(client)
    reply = client.post("/api/passport/finish", json={"proofs": [], "result": {}})
    assert reply.get_json()["ok"] is False
    with client.session_transaction() as s:
        assert "is_adult" not in s


def test_an_unreachable_service_is_a_502(passport_on, monkeypatch):
    def down(*_):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(site, "passport_check", down)
    client = site.app.test_client()
    open_page(client)
    assert client.post("/api/passport/finish", json={}).status_code == 502
    with client.session_transaction() as s:
        assert "passport_scope" in s  # an outage does not use up the visit's try


def test_every_visit_gets_its_own_scope(passport_on):
    assert open_page(site.app.test_client()) != open_page(site.app.test_client())


def test_a_proof_without_a_visit_is_refused_before_it_is_checked(passport_on, monkeypatch):
    monkeypatch.setattr(site, "passport_check", lambda *_: pytest.fail("should not be asked"))
    client = site.app.test_client()
    reply = client.post("/api/passport/finish", json={"proofs": ["p"], "result": {}})
    assert reply.status_code == 400
    with client.session_transaction() as s:
        assert "is_adult" not in s


def test_keeping_the_old_cookie_does_not_give_a_second_try(passport_on, monkeypatch):
    # The session is in the cookie, so a visitor can resend the cookie from before the finish.
    monkeypatch.setattr(site, "passport_check", lambda *_: True)
    client = site.app.test_client()
    open_page(client)
    old_cookie = client.get_cookie("session").value
    assert client.post("/api/passport/finish", json={}).get_json()["ok"] is True
    replay = site.app.test_client()
    replay.set_cookie("session", old_cookie)
    reply = replay.post("/api/passport/finish", json={})
    assert reply.status_code == 400
    with replay.session_transaction() as s:
        assert "is_adult" not in s


def test_a_visit_older_than_the_limit_is_refused(passport_on, monkeypatch):
    monkeypatch.setattr(site, "passport_check", lambda *_: pytest.fail("should not be asked"))
    client = site.app.test_client()
    open_page(client)
    with client.session_transaction() as s:
        s["passport_scope_at"] -= site.PASSPORT_VISIT_SECONDS + 1
    assert client.post("/api/passport/finish", json={}).status_code == 400


def test_an_outage_leaves_the_try_for_later(passport_on, monkeypatch):
    def down(*_):
        raise requests.ConnectionError("down")

    client = site.app.test_client()
    open_page(client)
    monkeypatch.setattr(site, "passport_check", down)
    assert client.post("/api/passport/finish", json={}).status_code == 502
    monkeypatch.setattr(site, "passport_check", lambda *_: True)
    assert client.post("/api/passport/finish", json={}).get_json()["ok"] is True


def test_a_visit_can_be_finished_only_once(passport_on, monkeypatch):
    monkeypatch.setattr(site, "passport_check", lambda *_: True)
    client = site.app.test_client()
    open_page(client)
    assert client.post("/api/passport/finish", json={}).get_json()["ok"] is True
    again = client.post("/api/passport/finish", json={})
    assert again.status_code == 400


def test_passport_check_asks_the_service(passport_on, monkeypatch):
    calls = {}

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def post(url, json, timeout):
        calls.update(url=url, json=json)
        return Reply()

    monkeypatch.setattr(site.requests, "post", post)
    assert site.passport_check(["p"], {"r": 1}, "localhost", "age-over-18:abc") is True
    assert calls == {
        "url": "http://passport:8100/verify",
        "json": {
            "proofs": ["p"],
            "result": {"r": 1},
            "domain": "localhost",
            "scope": "age-over-18:abc",
        },
    }


def test_the_client_script_is_fetched_once_and_served_as_javascript(passport_on, monkeypatch):
    fetched = []

    class Reply:
        content = b"console.log('client')"

        def raise_for_status(self):
            pass

    def get(url, timeout):
        fetched.append(url)
        return Reply()

    monkeypatch.setattr(site.requests, "get", get)
    client = site.app.test_client()
    first = client.get("/passport/client.js")
    client.get("/passport/client.js")
    assert first.mimetype == "text/javascript"
    assert first.data == b"console.log('client')"
    assert fetched == ["http://passport:8100/client.js"]


def test_the_client_script_is_a_502_when_the_service_is_down(passport_on, monkeypatch):
    def get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(site.requests, "get", get)
    assert site.app.test_client().get("/passport/client.js").status_code == 502


def test_passport_uploads_get_more_room_than_other_routes(passport_on, monkeypatch):
    monkeypatch.setattr(site, "passport_check", lambda *_: False)
    big = {"proofs": ["x" * (5 * 1024 * 1024)], "result": {}}
    client = site.app.test_client()
    open_page(client)
    assert client.post("/api/passport/finish", json=big).status_code == 200

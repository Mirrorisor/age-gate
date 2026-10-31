"""The standalone verification service (agecheck.service) and its tokens (agecheck.handoff)."""

from urllib.parse import parse_qs, urlsplit

import pytest

from agecheck import handoff
from agecheck.passport import PassportError
from agecheck.service import create_app

SECRET = "s" * 40
CALLBACK = "https://site.example/age-callback"
NONCE = "n" * 24


class FakeChecker:
    def __init__(self, verdict=True, down=False):
        self.verdict, self.down = verdict, down

    def check(self, proofs, result, domain, scope):
        if self.down:
            raise PassportError("down")
        return self.verdict

    def client_js(self):
        return b"console.log('client')"


def make_service(monkeypatch, verdict=True, **config):
    checker = FakeChecker(verdict)
    # The service builds its own PassportChecker from PASSPORT_URL; swap in the fake.
    monkeypatch.setattr("agecheck.flask_passport.PassportChecker", lambda url: checker)
    app = create_app({
        "CALLBACK_URL": CALLBACK, "SERVICE_SECRET": SECRET, "PASSPORT_URL": "http://passport:8100",
        "VERIFIER_URL": "", "RATE_LIMIT_PER_MIN": "0", **config,
    })
    return app.test_client(), checker


def pass_check(client, nonce=NONCE):
    assert client.get(f"/start?nonce={nonce}").status_code == 302
    client.post("/passport/start")
    return client.post("/passport/finish", json={"proofs": ["p"], "result": {}})


def token_from(response):
    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith(CALLBACK + "?")
    return parse_qs(urlsplit(location).query)["token"][0]


# ---- tokens ----------------------------------------------------------------------------------

def test_a_token_checks_out_for_its_nonce_and_origin():
    token = handoff.issue(SECRET, NONCE, "https://site.example", now=1000)
    payload = handoff.check(token, SECRET, NONCE, "https://site.example", now=1000)
    assert payload == {"v": 1, "over18": True, "nonce": NONCE, "aud": "https://site.example",
                       "exp": 1000 + handoff.TOKEN_SECONDS}


@pytest.mark.parametrize("change", ["secret", "nonce", "audience", "late", "tampered", "junk"])
def test_a_token_is_refused_when_anything_is_off(change):
    token = handoff.issue(SECRET, NONCE, "https://site.example", now=1000)
    secret, nonce, aud, now = SECRET, NONCE, "https://site.example", 1000
    if change == "secret":
        secret = "x" * 40
    elif change == "nonce":
        nonce = "m" * 24
    elif change == "audience":
        aud = "https://evil.example"
    elif change == "late":
        now = 1000 + handoff.TOKEN_SECONDS + 1
    elif change == "tampered":
        body, sig = token.split(".")
        token = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1] + "." + sig
    elif change == "junk":
        token = "not-a-token"
    with pytest.raises(handoff.TokenError):
        handoff.check(token, secret, nonce, aud, now=now)


# ---- the service -----------------------------------------------------------------------------

def test_it_refuses_to_start_without_a_proper_configuration():
    with pytest.raises(RuntimeError):
        create_app({"CALLBACK_URL": "not a url", "SERVICE_SECRET": SECRET, "PASSPORT_URL": "x"})
    with pytest.raises(RuntimeError):
        create_app({"CALLBACK_URL": CALLBACK, "SERVICE_SECRET": "short", "PASSPORT_URL": "x"})
    with pytest.raises(RuntimeError):
        create_app({"CALLBACK_URL": CALLBACK, "SERVICE_SECRET": SECRET, "PASSPORT_URL": "",
                    "VERIFIER_URL": ""})


def test_a_pass_hands_a_valid_token_to_the_configured_callback(monkeypatch):
    client, _ = make_service(monkeypatch)
    finished = pass_check(client)
    assert finished.get_json() == {"ok": True, "next": "/handoff"}
    token = token_from(client.get("/handoff"))
    handoff.check(token, SECRET, NONCE, "https://site.example")


def test_the_handoff_works_once_and_keeps_nothing(monkeypatch):
    client, _ = make_service(monkeypatch)
    pass_check(client)
    token_from(client.get("/handoff"))
    assert client.get("/handoff").status_code == 400
    assert client.get_cookie("agecheck_service") is None or "is_adult" not in str(
        client.get_cookie("agecheck_service").value)


def test_no_pass_no_token(monkeypatch):
    client, _ = make_service(monkeypatch, verdict=False)
    assert pass_check(client).get_json()["ok"] is False
    assert client.get("/handoff").status_code == 400


def test_a_handoff_without_start_is_refused(monkeypatch):
    client, _ = make_service(monkeypatch)
    client.post("/passport/start")
    client.post("/passport/finish", json={"proofs": ["p"], "result": {}})
    assert client.get("/handoff").status_code == 400  # passed, but no nonce from a site


@pytest.mark.parametrize("nonce", ["", "short", "has spaces in it!!", "x" * 129, "a/b" * 8])
def test_start_refuses_a_malformed_nonce(monkeypatch, nonce):
    client, _ = make_service(monkeypatch)
    assert client.get("/start", query_string={"nonce": nonce}).status_code == 400


def test_starting_again_forgets_an_earlier_pass(monkeypatch):
    client, _ = make_service(monkeypatch)
    pass_check(client)
    client.get("/start?nonce=" + "z" * 24)
    assert client.get("/handoff").status_code == 400  # the new check has not passed yet


def test_the_only_redirect_target_is_the_callback(monkeypatch):
    client, _ = make_service(monkeypatch)
    client.get("/start", query_string={"nonce": NONCE, "return_to": "https://evil.example/"})
    client.post("/passport/start")
    client.post("/passport/finish", json={"proofs": ["p"], "result": {}})
    assert client.get("/handoff").headers["Location"].startswith(CALLBACK + "?token=")


def test_with_one_method_start_goes_straight_to_it(monkeypatch):
    client, _ = make_service(monkeypatch)
    assert client.get(f"/start?nonce={NONCE}").headers["Location"].endswith("/passport/verify")


def test_with_two_methods_the_visitor_chooses(monkeypatch):
    client, _ = make_service(monkeypatch, VERIFIER_URL="http://verifier:8000")
    assert client.get(f"/start?nonce={NONCE}").headers["Location"].endswith("/choose")
    page = client.get("/choose").get_data(as_text=True)
    assert 'href="/passport/verify"' in page and 'href="/wallet/verify"' in page


def test_headers_keep_the_token_and_pages_safe(monkeypatch):
    client, _ = make_service(monkeypatch)
    pass_check(client)
    response = client.get("/handoff")
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    csp = client.get("/passport/verify").headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "connect-src 'self' wss:" in csp
    assert "connect-src 'self';" in client.get("/choose").headers["Content-Security-Policy"]


def test_its_cookie_has_its_own_name(monkeypatch):
    client, _ = make_service(monkeypatch)
    response = client.get(f"/start?nonce={NONCE}")
    assert "agecheck_service=" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]


def test_it_is_rate_limited(monkeypatch):
    client, _ = make_service(monkeypatch, RATE_LIMIT_PER_MIN="3")
    codes = [client.get(f"/start?nonce={NONCE}").status_code for _ in range(5)]
    assert codes == [302, 302, 302, 429, 429]

"""The reusable passport gate, mounted on a fresh Flask app as another site would."""

import pytest
from flask import Flask

from agecheck.flask_gate import AgeGate
from agecheck.flask_passport import PassportGate
from agecheck.passport import SCOPE_PREFIX, PassportError


class FakeChecker:
    def __init__(self, verdict=True, *, down=False):
        self.verdict = verdict
        self.down = down
        self.calls = []
        self.scripts_served = 0

    def check(self, proofs, result, domain, scope):
        if self.down:
            raise PassportError("down")
        self.calls.append((proofs, result, domain, scope))
        return self.verdict

    def client_js(self):
        if self.down:
            raise PassportError("down")
        self.scripts_served += 1
        return b"console.log('passport client')"


def make_site(checker=None, **options):
    app = Flask(__name__)
    app.secret_key = "k" * 32
    gate = PassportGate(checker=checker or FakeChecker(), domain="example.com", **options)
    app.register_blueprint(gate.blueprint)

    @app.route("/members")
    @gate.age_required
    def members():
        return "adults only"

    return app, gate


def start(client):
    return client.post("/passport-check/start").get_json()["scope"]


def finish(client):
    return client.post("/passport-check/finish", json={"proofs": ["p"], "result": {"age": 1}})


def test_a_visitor_who_has_not_passed_is_sent_to_the_passport_page():
    response = make_site()[0].test_client().get("/members")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/passport-check/verify")


def test_the_page_sets_no_cookie_and_has_no_inline_script():
    response = make_site()[0].test_client().get("/passport-check/verify")
    page = response.get_data(as_text=True)
    assert "Set-Cookie" not in response.headers
    assert '<script type="module" src="/passport-check/client.js"></script>' in page
    assert page.count("<script") == 1
    assert 'data-start="/passport-check/start"' in page


def test_passing_returns_to_the_protected_page_and_checks_this_sites_domain():
    checker = FakeChecker()
    client = make_site(checker)[0].test_client()
    client.get("/members")
    scope = start(client)
    assert scope.startswith(SCOPE_PREFIX)
    reply = finish(client).get_json()
    assert reply == {"ok": True, "next": "/members"}
    assert checker.calls == [(["p"], {"age": 1}, "example.com", scope)]
    assert client.get("/members").get_data(as_text=True) == "adults only"


def test_a_refused_proof_does_not_pass():
    client = make_site(FakeChecker(verdict=False))[0].test_client()
    start(client)
    assert finish(client).get_json()["ok"] is False
    assert client.get("/members").status_code == 302


def test_finish_without_start_is_refused_before_checking():
    checker = FakeChecker()
    client = make_site(checker)[0].test_client()
    assert finish(client).status_code == 400
    assert checker.calls == []


def test_resending_the_old_cookie_does_not_give_a_second_try():
    app = make_site()[0]
    client = app.test_client()
    start(client)
    old_cookie = client.get_cookie("session").value
    assert finish(client).get_json()["ok"] is True
    replay = app.test_client()
    replay.set_cookie("session", old_cookie)
    assert finish(replay).status_code == 400


def test_a_started_check_expires():
    client = make_site(visit_seconds=0)[0].test_client()
    start(client)
    assert finish(client).status_code == 400


def test_an_outage_is_a_502_and_keeps_the_try():
    checker = FakeChecker(down=True)
    client = make_site(checker)[0].test_client()
    start(client)
    assert finish(client).status_code == 502
    checker.down = False
    assert finish(client).get_json()["ok"] is True


def test_used_scopes_can_survive_a_restart(tmp_path):
    db = str(tmp_path / "scopes.db")
    app = make_site(scopes_db=db)[0]
    client = app.test_client()
    start(client)
    old_cookie = client.get_cookie("session").value
    finish(client)
    restarted = make_site(scopes_db=db)[0].test_client()
    restarted.set_cookie("session", old_cookie)
    assert finish(restarted).status_code == 400


def test_the_client_script_is_fetched_once_and_a_502_when_the_service_is_down():
    checker = FakeChecker()
    client = make_site(checker)[0].test_client()
    first = client.get("/passport-check/client.js")
    client.get("/passport-check/client.js")
    assert first.mimetype == "text/javascript"
    assert checker.scripts_served == 1
    down = make_site(FakeChecker(down=True))[0].test_client()
    assert down.get("/passport-check/client.js").status_code == 502


def test_dev_mode_is_on_by_default_and_can_be_turned_off():
    on = make_site()[0].test_client().get("/passport-check/verify").get_data(as_text=True)
    off = make_site(dev_mode=False)[0].test_client().get("/passport-check/verify")
    assert 'data-dev="1"' in on
    assert 'data-dev="0"' in off.get_data(as_text=True)


def test_the_wallet_and_passport_gates_share_one_pass():
    app = Flask(__name__)
    app.secret_key = "k" * 32
    wallet = AgeGate(verifier=object())
    passport = PassportGate(checker=FakeChecker(), domain="example.com")
    app.register_blueprint(wallet.blueprint)
    app.register_blueprint(passport.blueprint)

    @app.route("/members")
    @wallet.age_required
    def members():
        return "adults only"

    client = app.test_client()
    start(client)
    finish(client)
    assert client.get("/members").get_data(as_text=True) == "adults only"


@pytest.mark.parametrize("domain", ["", "https://example.com", "example.com/x", "example.com:443"])
def test_the_domain_must_be_a_bare_host_name(domain):
    with pytest.raises(ValueError):
        PassportGate(checker=FakeChecker(), domain=domain)


def test_give_exactly_one_of_url_or_checker():
    with pytest.raises(ValueError):
        PassportGate(domain="example.com")
    with pytest.raises(ValueError):
        PassportGate("http://x", checker=FakeChecker(), domain="example.com")

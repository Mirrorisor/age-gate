import pytest
from flask import Flask

from agecheck import VerifierError
from agecheck.flask_gate import AgeGate


class FakeVerifier:
    def __init__(self, verdict=(True, {"state": "verified"}), *, start_error=False,
                 finish_error=False):
        self.verdict = verdict
        self.start_error = start_error
        self.finish_error = finish_error
        self.finished_with = None

    def start_session(self):
        if self.start_error:
            raise VerifierError("down")
        return {"session_id": "sess-1", "offer": {"digital": {"requests": []}}}

    def finish(self, session_id, response):
        if self.finish_error:
            raise VerifierError("down")
        self.finished_with = (session_id, response)
        return self.verdict


def make_site(verifier=None, **options):
    app = Flask(__name__)
    app.secret_key = "k" * 32
    gate = AgeGate(verifier=verifier or FakeVerifier(), **options)
    app.register_blueprint(gate.blueprint)

    @app.route("/members")
    @gate.age_required
    def members():
        return "adults only"

    @app.route("/logout")
    def logout():
        gate.revoke()
        return "bye"

    return app, gate


def pass_the_check(client):
    assert client.post("/age/start").status_code == 200
    return client.post("/age/finish", json={"response": "proof"})


def test_a_visitor_who_has_not_passed_is_sent_to_the_gate():
    client = make_site()[0].test_client()
    response = client.get("/members")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/age/verify")


def test_passing_the_check_opens_the_page_and_returns_to_it():
    client = make_site()[0].test_client()
    client.get("/members?tab=2")
    reply = pass_the_check(client).get_json()
    assert reply == {"ok": True, "next": "/members?tab=2"}
    assert client.get("/members").get_data(as_text=True) == "adults only"


def test_going_straight_to_the_gate_lands_on_the_default_page():
    client = make_site(default_next="/welcome")[0].test_client()
    assert pass_the_check(client).get_json()["next"] == "/welcome"


def test_the_proof_goes_to_the_verifier_and_is_not_echoed_back():
    verifier = FakeVerifier()
    client = make_site(verifier)[0].test_client()
    reply = pass_the_check(client)
    assert verifier.finished_with == ("sess-1", "proof")
    assert "proof" not in reply.get_data(as_text=True)


def test_a_failed_check_gives_a_message_and_opens_nothing():
    verifier = FakeVerifier(verdict=(False, {"state": "failed", "reason": "untrusted-issuer"}))
    client = make_site(verifier)[0].test_client()
    reply = pass_the_check(client).get_json()
    assert reply["ok"] is False
    assert "does not trust" in reply["message"]
    assert client.get("/members").status_code == 302


def test_finishing_without_starting_says_to_reload():
    response = make_site()[0].test_client().post("/age/finish", json={"response": "x"})
    assert response.status_code == 400
    assert "Reload" in response.get_json()["message"]


def test_a_verifier_that_is_down_is_reported_not_crashed_on():
    start = make_site(FakeVerifier(start_error=True))[0].test_client().post("/age/start")
    assert start.status_code == 502
    client = make_site(FakeVerifier(finish_error=True))[0].test_client()
    assert client.post("/age/start").status_code == 200
    reply = client.post("/age/finish", json={"response": "x"})
    assert reply.status_code == 502
    assert "not reachable" in reply.get_json()["message"]


def test_a_session_can_only_be_finished_once():
    client = make_site()[0].test_client()
    assert pass_the_check(client).status_code == 200
    assert client.post("/age/finish", json={"response": "again"}).status_code == 400


@pytest.mark.parametrize(
    "bad", ["//evil.example/x", "https://evil.example/x", "/\\evil.example", "evil", "/a\nb"]
)
def test_the_gate_never_redirects_to_another_site(bad):
    app, gate = make_site(default_next="/home")
    client = app.test_client()
    client.post("/age/start")
    with client.session_transaction() as s:
        s[gate._pending_key] = bad
    assert client.post("/age/finish", json={"response": "p"}).get_json()["next"] == "/home"


def test_the_page_has_no_inline_script_or_handler():
    page = make_site()[0].test_client().get("/age/verify").get_data(as_text=True)
    assert "<script src=" in page
    assert "<script>" not in page
    assert "onclick" not in page
    assert 'data-start="/age/start"' in page


def test_the_script_is_served_as_javascript():
    response = make_site()[0].test_client().get("/age/verify.js")
    assert response.mimetype == "text/javascript"
    assert "navigator.credentials.get" in response.get_data(as_text=True)


def test_revoke_removes_the_pass():
    client = make_site()[0].test_client()
    pass_the_check(client)
    client.get("/logout")
    assert client.get("/members").status_code == 302


def test_the_session_holds_only_flags():
    client = make_site()[0].test_client()
    pass_the_check(client)
    with client.session_transaction() as s:
        assert set(s) == {"is_adult"}


def test_a_custom_url_prefix_and_session_key():
    app, gate = make_site(url_prefix="/over18", session_key="adult")
    client = app.test_client()
    assert client.get("/members").headers["Location"].endswith("/over18/verify")
    client.post("/over18/start")
    client.post("/over18/finish", json={"response": "p"})
    with client.session_transaction() as s:
        assert s.get("adult") is True


def test_exactly_one_of_url_or_verifier_is_required():
    with pytest.raises(ValueError):
        AgeGate()
    with pytest.raises(ValueError):
        AgeGate("http://x", verifier=FakeVerifier())
    assert AgeGate("http://127.0.0.1:8000").verifier.base_url == "http://127.0.0.1:8000"

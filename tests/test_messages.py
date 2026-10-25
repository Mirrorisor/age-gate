import app as site
from agecheck import VerifierError


def client_with_session():
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    return client


def test_failed_check_returns_a_friendly_message(monkeypatch):
    monkeypatch.setattr(
        site.verifier,
        "finish",
        lambda sid, response: (False, {"reason": "untrusted-issuer", "state": "failed"}),
    )
    data = client_with_session().post("/api/finish", json={"response": "x"}).get_json()
    assert data["ok"] is False
    assert "does not trust" in data["message"]
    assert data["detail"]["reason"] == "untrusted-issuer"  # raw detail is still returned


def test_missing_session_says_to_reload():
    response = site.app.test_client().post("/api/finish", json={"response": "x"})
    assert response.status_code == 400
    assert "Reload" in response.get_json()["message"]


def test_verifier_down_says_try_later(monkeypatch):
    def boom(sid, response):
        raise VerifierError("down")

    monkeypatch.setattr(site.verifier, "finish", boom)
    response = client_with_session().post("/api/finish", json={"response": "x"})
    assert response.status_code == 502
    assert "not reachable" in response.get_json()["message"]


def test_verified_check_has_no_message_and_opens_members(monkeypatch):
    monkeypatch.setattr(site.verifier, "finish", lambda sid, response: (True, {"state": "verified"}))
    client = client_with_session()
    data = client.post("/api/finish", json={"response": "x"}).get_json()
    assert data["ok"] is True
    assert "message" not in data
    assert client.get("/members").status_code == 200


def test_page_script_shows_the_message():
    page = site.app.test_client().get("/verify").get_data(as_text=True)
    assert "out.message" in page
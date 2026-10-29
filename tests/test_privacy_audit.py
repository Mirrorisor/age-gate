"""Checks that what the site stores and shows matches what /privacy says it does.

If one of these fails, either the site started collecting something new or the
privacy page needs to change. Do not just edit the test to make it pass.
"""

import re

import app as site
from agecheck.zecpay import InvoiceStore

# The only things the session cookie may ever hold. None of them is personal data.
ALLOWED_SESSION_KEYS = {"av_session", "is_adult", "invoice_id"}

PROOF = "wallet-proof-" + "p" * 200  # stands in for the wallet's zero-knowledge proof


class QuietCheckout:
    def create_invoice(self, amount_zec, order_id, expires_in_secs=1800):
        return {
            "id": "inv-1",
            "amount_zat": 100000,
            "address": "utest1addr",
            "payment_uri": "zcash:utest1addr?amount=0.001",
        }

    def get_invoice(self, invoice_id):
        return {"id": invoice_id, "status": "paid"}


def session_contents(client):
    """Decode the signed session cookie the way the server does."""
    cookie = client.get_cookie("session")
    serializer = site.app.session_interface.get_signing_serializer(site.app)
    return serializer.loads(cookie.value) if cookie else {}


def full_flow(monkeypatch, payment=False):
    """Run the age check (and optionally the payment page) with a stubbed verifier."""
    seen = {}

    def finish(sid, response):
        seen["response"] = response
        return True, {"state": "verified", "result": {"age_over_18": True}}

    monkeypatch.setattr(
        site.verifier, "start_session", lambda: {"session_id": "sess-1", "offer": {"x": 1}}
    )
    monkeypatch.setattr(site.verifier, "finish", finish)
    if payment:
        monkeypatch.setattr(site, "PAYMENT_GATE", True)
        monkeypatch.setattr(site, "zec", QuietCheckout())
        monkeypatch.setattr(site, "invoices", InvoiceStore())
    client = site.app.test_client()
    assert client.post("/api/start").status_code == 200
    reply = client.post("/api/finish", json={"response": PROOF})
    assert reply.status_code == 200
    if payment:
        assert client.get("/pay").status_code == 200
    return client, reply, seen


def test_the_session_cookie_holds_only_allowed_keys(monkeypatch):
    client, _, _ = full_flow(monkeypatch, payment=True)
    contents = session_contents(client)
    assert contents  # the flow really did set a cookie
    assert set(contents) <= ALLOWED_SESSION_KEYS


def test_the_session_cookie_never_contains_the_proof_or_any_claim(monkeypatch):
    client, _, _ = full_flow(monkeypatch, payment=True)
    text = repr(session_contents(client)).lower()
    for secret in ("wallet-proof", "birth", "name", "document", "age_over", "result"):
        assert secret not in text


def test_the_proof_is_passed_on_and_not_echoed_back(monkeypatch):
    _, reply, seen = full_flow(monkeypatch)
    assert seen["response"] == PROOF  # forwarded to the verifier, which is its job
    assert PROOF not in reply.get_data(as_text=True)


def test_logging_out_removes_the_passed_flag(monkeypatch):
    client, _, _ = full_flow(monkeypatch)
    client.get("/logout")
    assert "is_adult" not in session_contents(client)


def test_logging_out_forgets_the_invoice_too(monkeypatch):
    """The next person on a shared browser must not inherit a paid invoice."""
    client, _, _ = full_flow(monkeypatch, payment=True)
    site.invoices.record("inv-1", "evt-1", 1, "paid")
    assert client.get("/members").status_code == 200
    client.get("/logout")
    assert session_contents(client) == {}
    client.post("/api/start")
    client.post("/api/finish", json={"response": PROOF})
    reply = client.get("/members")
    assert reply.status_code == 302
    assert reply.headers["Location"].endswith("/pay")


PUBLIC_PAGES = ["/", "/verify", "/privacy", "/health"]


def test_no_page_loads_anything_from_another_site(monkeypatch):
    client, _, _ = full_flow(monkeypatch, payment=True)
    monkeypatch.setattr(site.verifier, "health", lambda: {"zk_age_verifier": "test"})
    pages = {path: client.get(path).get_data(as_text=True) for path in PUBLIC_PAGES}
    pages["/members"] = client.get("/members").get_data(as_text=True)
    pages["/pay"] = client.get("/pay").get_data(as_text=True)
    external = re.compile(r"""(?:src|href|action)\s*=\s*["']\s*(?:https?:)?//""", re.I)
    for path, page in pages.items():
        assert not external.search(page), path
        assert "url(" not in page, path
        assert "@import" not in page, path


def test_the_browser_is_told_not_to_leak_where_you_came_from():
    for path in PUBLIC_PAGES:
        response = site.app.test_client().get(path)
        assert response.headers["Referrer-Policy"] == "no-referrer", path


def test_the_site_never_sets_a_cookie_just_for_visiting():
    for path in ("/", "/verify", "/privacy"):
        assert "Set-Cookie" not in site.app.test_client().get(path).headers, path


def test_the_privacy_page_states_the_limits_honestly():
    page = site.app.test_client().get("/privacy").get_data(as_text=True)
    assert "experimental" in page
    assert "test certificates" in page
    assert "no accounts" in page.lower()


def test_the_pay_page_says_to_pay_from_a_shielded_balance(monkeypatch):
    client, _, _ = full_flow(monkeypatch, payment=True)
    assert "shielded balance" in client.get("/pay").get_data(as_text=True)


def test_the_privacy_page_says_the_verifier_sees_the_issuer():
    page = site.app.test_client().get("/privacy").get_data(as_text=True)
    assert "which organisation issued your credential" in page

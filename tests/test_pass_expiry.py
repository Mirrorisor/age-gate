"""A pass lasts PASS_HOURS, and a payment never unlocks anything without a known amount."""

import json
import time

import app as site
from agecheck.zecpay import InvoiceStore, sign_webhook

SECRET = "w" * 32


def client_with(**values):
    client = site.app.test_client()
    with client.session_transaction() as s:
        s.update(values)
    return client


def test_a_current_pass_opens_members():
    client = client_with(is_adult=True, adult_until=int(time.time()) + 60)
    assert client.get("/members").status_code == 200


def test_an_expired_pass_does_not():
    client = client_with(is_adult=True, adult_until=int(time.time()) - 1)
    assert client.get("/members").status_code == 302


def test_a_pass_without_an_end_does_not():
    # A cookie made before passes had an end, or copied and edited, counts as no pass.
    assert client_with(is_adult=True).get("/members").status_code == 302
    assert client_with(is_adult=True, adult_until=True).get("/members").status_code == 302
    assert client_with(is_adult=True, adult_until="9999999999").get("/members").status_code == 302
    assert client_with(adult_until=int(time.time()) + 60).get("/members").status_code == 302


def test_passing_gives_a_pass_of_pass_hours(monkeypatch):
    class Verifier:
        def finish(self, sid, response):
            return True, {}

    monkeypatch.setattr(site, "verifier", Verifier())
    client = client_with(av_session="s1")
    before = time.time()
    assert client.post("/api/finish", json={"response": "r"}).get_json()["ok"] is True
    with client.session_transaction() as s:
        assert s["is_adult"] is True
        assert before + site.PASS_SECONDS - 5 <= s["adult_until"] <= time.time() + site.PASS_SECONDS


def test_the_pass_ends_after_pass_hours(monkeypatch):
    client = client_with(is_adult=True, adult_until=int(time.time()) + 60)
    later = time.time() + 61
    monkeypatch.setattr(site.time, "time", lambda: later)
    assert client.get("/members").status_code == 302


def test_the_privacy_page_says_how_long_a_pass_lasts():
    page = site.app.test_client().get("/privacy").get_data(as_text=True)
    assert f"the pass lasts {site.PASS_SECONDS / 3600:g} hours" in page


class Checkout:
    def __init__(self, amount_zat=100000, server=None):
        self.amount_zat = amount_zat
        self.server = server or {"id": "inv-1", "status": "paid", "amount_zat": 100000}

    def create_invoice(self, amount_zec, order_id, expires_in_secs=1800):
        return {"id": "inv-1", "amount_zat": self.amount_zat, "address": "utest1a",
                "payment_uri": "zcash:utest1a?amount=0.001"}

    def get_invoice(self, invoice_id):
        return self.server


def gate_on(monkeypatch, checkout):
    monkeypatch.setattr(site, "PAYMENT_GATE", True)
    monkeypatch.setattr(site, "ZC_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(site, "zec", checkout)
    monkeypatch.setattr(site, "invoices", InvoiceStore())
    return client_with(is_adult=True, adult_until=int(time.time()) + 3600)


def paid_webhook(client, amount_zat=100000, confirmed_zat=100000):
    raw = json.dumps({
        "event": "invoice.paid", "event_id": "ev1", "seq": 1,
        "invoice": {"id": "inv-1", "status": "paid", "amount_zat": amount_zat,
                    "confirmed_zat": confirmed_zat},
    }).encode()
    return client.post("/webhooks/zeccheckout", data=raw, headers={
        "ZecCheckout-Signature": sign_webhook(SECRET, raw), "Content-Type": "application/json"})


def test_an_invoice_without_an_amount_is_never_offered(monkeypatch):
    for amount in (None, "100000", 0, -5, True):
        client = gate_on(monkeypatch, Checkout(amount_zat=amount))
        assert client.get("/pay").status_code == 502
        assert site.invoices.get("inv-1") is None


def test_an_invoice_recorded_without_an_amount_unlocks_nothing(monkeypatch):
    client = gate_on(monkeypatch, Checkout())
    site.invoices.add("inv-1", None, "zcash:utest1a", "utest1a")
    with client.session_transaction() as s:
        s["invoice_id"] = "inv-1"
    assert paid_webhook(client).get_json() == {"ignored": True}
    assert client.get("/members").status_code == 302


def test_the_checkout_servers_own_amount_must_match(monkeypatch):
    server = {"id": "inv-1", "status": "paid", "amount_zat": 1}
    client = gate_on(monkeypatch, Checkout(server=server))
    client.get("/pay")
    assert paid_webhook(client).get_json() == {"ignored": True}
    assert client.get("/members").status_code == 302


def test_a_matching_payment_still_unlocks(monkeypatch):
    client = gate_on(monkeypatch, Checkout())
    client.get("/pay")
    assert paid_webhook(client).get_json() == {"ok": True}
    assert client.get("/members").status_code == 200

import json
import time

import app as site
from agecheck import zecpay
from agecheck.zecpay import (
    InvoiceStore,
    PaymentError,
    ZecCheckoutClient,
    sign_webhook,
    verify_webhook,
)

SECRET = "s" * 32
API_KEY = "k" * 32


# ---------- signature checking ----------


def test_valid_signature_is_accepted():
    body = b'{"a": 1}'
    assert verify_webhook(SECRET, sign_webhook(SECRET, body), body)


def test_wrong_secret_tampered_body_and_missing_header_are_rejected():
    body = b'{"a": 1}'
    header = sign_webhook(SECRET, body)
    assert not verify_webhook("x" * 32, header, body)
    assert not verify_webhook(SECRET, header, b'{"a": 2}')
    assert not verify_webhook(SECRET, None, body)
    assert not verify_webhook(SECRET, "", body)
    assert not verify_webhook("", header, body)


def test_stale_and_far_future_timestamps_are_rejected_but_recent_ones_pass():
    body = b"{}"
    now = 1_000_000
    assert verify_webhook(SECRET, sign_webhook(SECRET, body, now - 299), body, now=now)
    assert not verify_webhook(SECRET, sign_webhook(SECRET, body, now - 301), body, now=now)
    assert not verify_webhook(SECRET, sign_webhook(SECRET, body, now + 301), body, now=now)


def test_malformed_headers_never_raise_and_are_rejected():
    body = b"{}"
    for header in ["garbage", "t=abc,v1=00", "t=1", "v1=00", "t=,v1=", "t=1,v1=\u00e9\u00e9"]:
        assert not verify_webhook(SECRET, header, body, now=1)


def test_first_value_wins_so_a_second_v1_cannot_be_smuggled_in():
    body = b"{}"
    good = sign_webhook(SECRET, body, 1000)
    t, _, mac = good.partition(",v1=")
    forged = f"{t},v1=deadbeef,v1={mac}"
    assert not verify_webhook(SECRET, forged, body, now=1000)


# ---------- client ----------


class FakeResponse:
    def __init__(self, status=201, data=None, bad_json=False):
        self.status_code = status
        self._data = data
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._data


def test_create_invoice_sends_bearer_key_and_body(monkeypatch):
    seen = {}

    def fake(method, url, headers=None, json=None, timeout=None):
        seen.update(method=method, url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(201, {"id": "inv1", "status": "pending"})

    monkeypatch.setattr(zecpay.requests, "request", fake)
    client = ZecCheckoutClient("http://zc:8080/", API_KEY)
    assert client.create_invoice("0.001", "ord_1")["id"] == "inv1"
    assert seen["method"] == "POST"
    assert seen["url"] == "http://zc:8080/api/v1/invoices"
    assert seen["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert seen["json"]["order_id"] == "ord_1"
    assert seen["timeout"]


def test_client_turns_every_failure_into_payment_error(monkeypatch):
    client = ZecCheckoutClient("http://zc", API_KEY)
    cases = [
        FakeResponse(500, {}),
        FakeResponse(401, {}),
        FakeResponse(201, bad_json=True),
        FakeResponse(201, {"no_id": True}),
        FakeResponse(201, ["not", "a", "dict"]),
    ]
    for case in cases:
        monkeypatch.setattr(zecpay.requests, "request", lambda *a, _c=case, **k: _c)
        try:
            client.get_invoice("x")
        except PaymentError:
            continue
        raise AssertionError("expected PaymentError")

    def boom(*a, **k):
        raise zecpay.requests.ConnectionError("down")

    monkeypatch.setattr(zecpay.requests, "request", boom)
    try:
        client.get_invoice("x")
    except PaymentError:
        pass
    else:
        raise AssertionError("expected PaymentError")


# ---------- invoice store ----------


def test_store_orders_events_and_keeps_paid_final():
    store = InvoiceStore()
    store.add("i1", 100, "zcash:u1", "u1")
    assert store.is_new_event("i1", "e1", 1)
    store.record("i1", "e1", 1, "detected")
    assert not store.is_new_event("i1", "e1", 2)  # same event id
    assert not store.is_new_event("i1", "e2", 1)  # not newer
    assert store.is_new_event("i1", "e3", 2)
    store.record("i1", "e3", 2, "paid")
    store.record("i1", "e4", 3, "expired")
    assert store.is_paid("i1")
    assert store.get("i1")["status"] == "paid"
    assert not store.is_new_event("nope", "e1", 1)
    assert store.get(None) is None and not store.is_paid(["x"])


# ---------- the site ----------


class FakeCheckout:
    def __init__(self):
        self.created = 0
        self.truth = {"status": "paid"}
        self.fail_lookup = False
        self.fail_create = False

    def create_invoice(self, amount_zec, order_id, expires_in_secs=1800):
        if self.fail_create:
            raise PaymentError("down")
        self.created += 1
        return {
            "id": "inv-1",
            "status": "pending",
            "amount_zat": 100000,
            "address": "utest1addr<script>",
            "payment_uri": "zcash:utest1addr?amount=0.001",
        }

    def get_invoice(self, invoice_id):
        if self.fail_lookup:
            raise PaymentError("down")
        return dict(self.truth, id=invoice_id)


def gate_on(monkeypatch, fake=None):
    fake = fake or FakeCheckout()
    monkeypatch.setattr(site, "PAYMENT_GATE", True)
    monkeypatch.setattr(site, "ZC_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(site, "zec", fake)
    monkeypatch.setattr(site, "invoices", InvoiceStore())
    return fake


def adult_client():
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["is_adult"] = True
    return client


def send(client, event, status="paid", event_id="ev1", seq=1, secret=SECRET, invoice=None, stamp=None):
    payload = {
        "event": event,
        "event_id": event_id,
        "seq": seq,
        "invoice": invoice
        or {"id": "inv-1", "status": status, "amount_zat": 100000, "confirmed_zat": 100000},
    }
    raw = json.dumps(payload).encode()
    header = sign_webhook(secret, raw, int(time.time()) if stamp is None else stamp)
    return client.post(
        "/webhooks/zeccheckout",
        data=raw,
        headers={"ZecCheckout-Signature": header, "Content-Type": "application/json"},
    )


def test_gate_is_off_by_default_so_members_only_needs_the_age_check():
    assert site.PAYMENT_GATE is False
    assert adult_client().get("/members").status_code == 200


def test_unpaid_adult_is_sent_to_pay_and_not_to_members(monkeypatch):
    gate_on(monkeypatch)
    response = adult_client().get("/members")
    assert response.status_code == 302 and response.headers["Location"].endswith("/pay")


def test_pay_requires_the_age_check_first(monkeypatch):
    gate_on(monkeypatch)
    response = site.app.test_client().get("/pay")
    assert response.status_code == 302 and response.headers["Location"].endswith("/verify")


def test_pay_page_creates_one_invoice_and_escapes_everything(monkeypatch):
    fake = gate_on(monkeypatch)
    client = adult_client()
    page = client.get("/pay").get_data(as_text=True)
    client.get("/pay")
    assert fake.created == 1
    assert "<script>" not in page.split("<code>")[1].split("</code>")[0]
    assert "utest1addr&lt;script&gt;" in page
    assert 'href="zcash:utest1addr?amount=0.001"' in page


def test_non_zcash_payment_uri_gets_no_link(monkeypatch):
    fake = gate_on(monkeypatch)
    fake.create_invoice = lambda *a, **k: {
        "id": "inv-1", "amount_zat": 1, "address": "a", "payment_uri": "javascript:alert(1)"
    }
    page = adult_client().get("/pay").get_data(as_text=True)
    assert "javascript:" not in page


def test_pay_reports_a_down_checkout_server(monkeypatch):
    fake = gate_on(monkeypatch)
    fake.fail_create = True
    assert adult_client().get("/pay").status_code == 502


def test_signed_paid_webhook_unlocks_members(monkeypatch):
    gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    assert send(client, "invoice.paid").status_code == 200
    assert client.get("/pay/status").get_json()["status"] == "paid"
    assert client.get("/members").status_code == 200


def test_bad_signature_changes_nothing(monkeypatch):
    gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    assert send(client, "invoice.paid", secret="x" * 32).status_code == 400
    assert send(client, "invoice.paid", stamp=int(time.time()) - 1000).status_code == 400
    assert client.get("/pay/status").get_json()["status"] == "pending"
    assert client.get("/members").status_code == 302


def test_replayed_and_older_events_are_ignored(monkeypatch):
    gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    assert send(client, "invoice.detected", status="detected", event_id="a", seq=5).status_code == 200
    assert client.get("/pay/status").get_json()["status"] == "detected"
    assert send(client, "invoice.pending", status="pending", event_id="b", seq=4).get_json() == {"ignored": True}
    assert send(client, "invoice.detected", status="detected", event_id="a", seq=6).get_json() == {"ignored": True}
    assert client.get("/pay/status").get_json()["status"] == "detected"


def test_paid_webhook_is_not_enough_if_the_server_disagrees(monkeypatch):
    fake = gate_on(monkeypatch)
    fake.truth = {"status": "pending"}
    client = adult_client()
    client.get("/pay")
    assert send(client, "invoice.paid").get_json() == {"ignored": True}
    assert client.get("/members").status_code == 302


def test_lookup_failure_asks_the_sender_to_retry_and_does_not_unlock(monkeypatch):
    fake = gate_on(monkeypatch)
    fake.fail_lookup = True
    client = adult_client()
    client.get("/pay")
    assert send(client, "invoice.paid").status_code == 503
    assert client.get("/members").status_code == 302
    fake.fail_lookup = False
    assert send(client, "invoice.paid").status_code == 200  # same event id, now accepted
    assert client.get("/members").status_code == 200


def test_wrong_or_short_amount_does_not_unlock(monkeypatch):
    gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    short = {"id": "inv-1", "status": "paid", "amount_zat": 100000, "confirmed_zat": 5}
    assert send(client, "invoice.paid", invoice=short).get_json() == {"ignored": True}
    other = {"id": "inv-1", "status": "paid", "amount_zat": 1, "confirmed_zat": 1}
    assert send(client, "invoice.paid", invoice=other, event_id="ev2", seq=2).get_json() == {"ignored": True}
    assert client.get("/members").status_code == 302


def test_unknown_invoice_and_malformed_bodies(monkeypatch):
    gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    ghost = {"id": "someone-else", "status": "paid", "amount_zat": 1, "confirmed_zat": 1}
    assert send(client, "invoice.paid", invoice=ghost).get_json() == {"ignored": True}
    raw = b"not json"
    header = sign_webhook(SECRET, raw)
    response = client.post("/webhooks/zeccheckout", data=raw, headers={"ZecCheckout-Signature": header})
    assert response.status_code == 400
    raw = json.dumps({"event": 1, "event_id": 2, "invoice": {"id": 3, "status": 4}}).encode()
    header = sign_webhook(SECRET, raw)
    response = client.post("/webhooks/zeccheckout", data=raw, headers={"ZecCheckout-Signature": header})
    assert response.status_code == 400


def test_one_visitors_payment_does_not_unlock_another(monkeypatch):
    gate_on(monkeypatch)
    payer = adult_client()
    payer.get("/pay")
    send(payer, "invoice.paid")
    other = adult_client()
    assert other.get("/members").status_code == 302
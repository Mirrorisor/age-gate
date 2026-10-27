import json
import os
import subprocess
import sys
import time
from pathlib import Path

import app as site
from agecheck.zecpay import InvoiceStore, sign_webhook

SECRET = "s" * 32
ROOT = Path(__file__).resolve().parent.parent


class CountingCheckout:
    """Hands out a new invoice id each time and confirms every invoice as paid."""

    def __init__(self):
        self.created = 0

    def create_invoice(self, amount_zec, order_id, expires_in_secs=1800):
        self.created += 1
        return {
            "id": f"inv-{self.created}",
            "amount_zat": 100000,
            "address": "utest1addr",
            "payment_uri": "zcash:utest1addr?amount=0.001",
        }

    def get_invoice(self, invoice_id):
        return {"id": invoice_id, "status": "paid"}


def gate_on(monkeypatch):
    fake = CountingCheckout()
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


def send(client, invoice_id, status, event_id, seq):
    payload = {
        "event": "invoice." + status,
        "event_id": event_id,
        "seq": seq,
        "invoice": {"id": invoice_id, "status": status, "amount_zat": 100000, "confirmed_zat": 100000},
    }
    raw = json.dumps(payload).encode()
    header = sign_webhook(SECRET, raw, int(time.time()))
    return client.post(
        "/webhooks/zeccheckout",
        data=raw,
        headers={"ZecCheckout-Signature": header, "Content-Type": "application/json"},
    )


def test_an_expired_invoice_is_replaced_with_a_fresh_one(monkeypatch):
    fake = gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    assert send(client, "inv-1", "expired", "e1", 1).status_code == 200
    assert client.get("/pay/status").get_json()["status"] == "expired"
    page = client.get("/pay").get_data(as_text=True)
    assert fake.created == 2
    assert "Payment" in page
    assert client.get("/pay/status").get_json()["status"] == "pending"


def test_a_paid_invoice_is_never_replaced(monkeypatch):
    fake = gate_on(monkeypatch)
    client = adult_client()
    client.get("/pay")
    assert send(client, "inv-1", "paid", "e1", 1).status_code == 200
    assert client.get("/pay").status_code == 302
    assert fake.created == 1
    assert client.get("/members").status_code == 200


def run_site(extra_env):
    env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "PAYMENT_GATE")}
    env.update(extra_env)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    return subprocess.run(
        [sys.executable, "-c", "import app"], cwd=ROOT, env=env, capture_output=True, text=True
    )


GATE = {"PAYMENT_GATE": "1", "ZC_API_KEY": "k" * 32, "ZC_WEBHOOK_SECRET": "s" * 32, "INVOICE_DB": ":memory:"}


def test_gate_refuses_to_start_with_the_placeholder_secret():
    result = run_site(GATE)
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_gate_starts_with_a_real_secret_and_site_starts_without_the_gate():
    assert run_site(dict(GATE, SECRET_KEY="r" * 40)).returncode == 0
    assert run_site({}).returncode == 0

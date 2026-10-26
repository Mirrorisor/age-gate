"""A FAKE ZecCheckout server for trying the payment gate without any wallet or coins.

It pretends to be the checkout server: it hands out invoices, and a button on its own
page "pays" them by sending your site a correctly signed webhook. Nothing here touches
a blockchain or real money. It listens on 127.0.0.1 only.

Run (in its own window):
    set these first (24+ characters each):  ZC_API_KEY, ZC_WEBHOOK_SECRET
    optional: ZC_WEBHOOK_URL (default http://localhost:5000/webhooks/zeccheckout), FAKE_PORT (default 8080)
    python scripts\\fake_zeccheckout.py
"""

from __future__ import annotations

import hmac
import html
import json
import os
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, jsonify, request

from agecheck.zecpay import sign_webhook

API_KEY = os.environ.get("ZC_API_KEY", "")
WEBHOOK_SECRET = os.environ.get("ZC_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.environ.get("ZC_WEBHOOK_URL", "http://localhost:5000/webhooks/zeccheckout")

app = Flask(__name__)
INVOICES: dict[str, dict] = {}
SEQ = {"n": 0}


def _authorised() -> bool:
    header = request.headers.get("Authorization", "")
    expected = f"Bearer {API_KEY}"
    return bool(API_KEY) and hmac.compare_digest(header.encode(), expected.encode())


def _public(invoice: dict) -> dict:
    return {k: v for k, v in invoice.items() if not k.startswith("_")}


@app.post("/api/v1/invoices")
def create_invoice():
    if not _authorised():
        return jsonify({"error": "unauthorised"}), 401
    body = request.get_json(silent=True) or {}
    try:
        amount_zec = Decimal(str(body.get("amount_zec")))
        amount_zat = int(amount_zec * 100_000_000)
    except (InvalidOperation, ValueError):
        return jsonify({"error": "bad amount"}), 400
    if amount_zat <= 0:
        return jsonify({"error": "bad amount"}), 400
    invoice_id = uuid.uuid4().hex
    address = "utest1FAKE" + uuid.uuid4().hex
    invoice = {
        "id": invoice_id,
        "status": "pending",
        "amount_zat": amount_zat,
        "amount_zec": str(amount_zec),
        "address": address,
        "payment_uri": f"zcash:{address}?amount={amount_zec}",
        "checkout_url": f"http://127.0.0.1:{os.environ.get('FAKE_PORT', '8080')}/fake/",
        "expires_at": int(time.time()) + int(body.get("expires_in_secs", 1800)),
        "_order_id": str(body.get("order_id", "")),
    }
    INVOICES[invoice_id] = invoice
    return jsonify(_public(invoice)), 201


@app.get("/api/v1/invoices/<invoice_id>")
def get_invoice(invoice_id):
    if not _authorised():
        return jsonify({"error": "unauthorised"}), 401
    invoice = INVOICES.get(invoice_id)
    if invoice is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_public(invoice))


def _send_event(invoice: dict, event: str, status: str) -> str:
    SEQ["n"] += 1
    payload = {
        "event": event,
        "event_id": uuid.uuid4().hex,
        "seq": SEQ["n"],
        "created": int(time.time()),
        "invoice": {
            "id": invoice["id"],
            "order_id": invoice["_order_id"],
            "status": status,
            "amount_zat": invoice["amount_zat"],
            "amount_zec": invoice["amount_zec"],
            "received_zat": invoice["amount_zat"],
            "confirmed_zat": invoice["amount_zat"] if status == "paid" else 0,
            "paid_at": int(time.time()) if status == "paid" else None,
        },
    }
    raw = json.dumps(payload).encode()
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "ZecCheckout-Signature": sign_webhook(WEBHOOK_SECRET, raw),
            },
            timeout=10,
            allow_redirects=False,
        )
        return f"{event}: your site answered {response.status_code}"
    except requests.RequestException as exc:
        return f"{event}: could not reach your site ({type(exc).__name__})"


@app.post("/fake/pay/<invoice_id>")
def fake_pay(invoice_id):
    invoice = INVOICES.get(invoice_id)
    if invoice is None:
        return "Unknown invoice", 404
    invoice["status"] = "detected"
    first = _send_event(invoice, "invoice.detected", "detected")
    invoice["status"] = "paid"
    second = _send_event(invoice, "invoice.paid", "paid")
    return (
        "<h1>Fake payment sent</h1><pre>"
        + html.escape(first + "\n" + second)
        + '</pre><p><a href="/fake/">Back</a></p>'
    )


@app.get("/fake/")
def fake_home():
    rows = ""
    for invoice in INVOICES.values():
        rows += (
            "<tr><td>" + html.escape(invoice["id"][:10]) + "</td><td>"
            + html.escape(invoice["status"]) + "</td><td>"
            + html.escape(invoice["amount_zec"]) + " ZEC</td><td>"
            f'<form method="post" action="/fake/pay/{html.escape(invoice["id"])}">'
            '<button>Simulate payment</button></form></td></tr>'
        )
    return (
        "<h1>FAKE checkout server</h1>"
        "<p><b>For local testing only. No blockchain, no real money.</b></p>"
        "<table border=1 cellpadding=6><tr><th>Invoice</th><th>Status</th><th>Amount</th><th></th></tr>"
        + rows + "</table>"
    )


if __name__ == "__main__":
    if len(API_KEY) < 24 or len(WEBHOOK_SECRET) < 24:
        sys.exit("Set ZC_API_KEY and ZC_WEBHOOK_SECRET (24+ characters each) first.")
    app.run(host="127.0.0.1", port=int(os.environ.get("FAKE_PORT", "8080")))
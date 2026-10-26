"""Helpers for taking a shielded Zcash payment through a ZecCheckout server.

Three small pieces, none of which touch a spending key:

* ``ZecCheckoutClient``: asks the checkout server for an invoice and reads one back.
* ``verify_webhook``: checks the signature on the server's "payment status changed"
  message (HMAC-SHA256 over ``"<timestamp>." + raw body``) and rejects stale ones.
* ``InvoiceStore``: remembers which invoices exist and which are paid, in memory.

Testnet demo code. The store forgets everything on restart; a real site needs a
database.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time

import requests


class PaymentError(Exception):
    """The checkout server could not be reached or gave an unusable answer."""


def sign_webhook(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Build a ``ZecCheckout-Signature`` header value (used by tests and the fake server)."""
    stamp = int(time.time()) if timestamp is None else int(timestamp)
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={mac}"


def verify_webhook(
    secret: str,
    header: str | None,
    body: bytes,
    *,
    now: float | None = None,
    tolerance: int = 300,
) -> bool:
    """Return True only for a correctly signed, recent webhook body."""
    if not secret or not header:
        return False
    parts: dict[str, str] = {}
    for item in header.split(","):
        key, sep, value = item.strip().partition("=")
        if sep:
            parts.setdefault(key, value)
    try:
        stamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    candidate = parts.get("v1")
    if not candidate:
        return False
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), candidate.encode())


class ZecCheckoutClient:
    """Minimal client for a ZecCheckout merchant API."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = requests.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code not in (200, 201):
                raise PaymentError(f"checkout server answered {response.status_code}")
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PaymentError(f"checkout server unavailable: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise PaymentError("checkout server sent an unexpected answer")
        return data

    def create_invoice(self, amount_zec: str, order_id: str, expires_in_secs: int = 1800) -> dict:
        return self._request(
            "POST",
            "/api/v1/invoices",
            {"amount_zec": amount_zec, "order_id": order_id, "expires_in_secs": expires_in_secs},
        )

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("GET", f"/api/v1/invoices/{invoice_id}")


class InvoiceStore:
    """In-memory record of invoices, their status, and the webhook events already applied."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._invoices: dict[str, dict] = {}

    def add(self, invoice_id: str, amount_zat, payment_uri: str, address: str) -> None:
        with self._lock:
            self._invoices[invoice_id] = {
                "status": "pending",
                "amount_zat": amount_zat,
                "payment_uri": payment_uri,
                "address": address,
                "seq": -1,
                "events": set(),
            }

    def get(self, invoice_id) -> dict | None:
        with self._lock:
            record = self._invoices.get(invoice_id) if isinstance(invoice_id, str) else None
            return None if record is None else {k: v for k, v in record.items() if k != "events"}

    def is_paid(self, invoice_id) -> bool:
        record = self.get(invoice_id)
        return bool(record and record["status"] == "paid")

    def is_new_event(self, invoice_id: str, event_id: str, seq) -> bool:
        """True unless this event was already applied or is older than one that was."""
        with self._lock:
            record = self._invoices.get(invoice_id)
            if record is None or event_id in record["events"]:
                return False
            return not (isinstance(seq, int) and seq <= record["seq"])

    def record(self, invoice_id: str, event_id: str, seq, status: str) -> None:
        """Remember an event and move the status on. ``paid`` is final."""
        with self._lock:
            record = self._invoices.get(invoice_id)
            if record is None:
                return
            record["events"].add(event_id)
            if isinstance(seq, int):
                record["seq"] = max(record["seq"], seq)
            if record["status"] != "paid":
                record["status"] = status
"""Helpers for taking a shielded Zcash payment through a ZecCheckout server.

Three small pieces, none of which touch a spending key:

* ``ZecCheckoutClient``: asks the checkout server for an invoice and reads one back.
* ``verify_webhook``: checks the signature on the server's "payment status changed"
  message (HMAC-SHA256 over ``"<timestamp>." + raw body``) and rejects stale ones.
* ``InvoiceStore``: remembers which invoices exist and which are paid, in a small
  SQLite file (or in memory when no file is given).

Testnet demo code. The SQLite file suits one site process; a busier site would want
a proper database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
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
    """Record of invoices, their status, and the webhook events already applied.

    With a file path the record lives in a SQLite file and survives restarts.
    Without one (``None``) it lives in memory only, which is what the tests use.
    """

    def __init__(self, path: str | None = None) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS invoices ("
                "id TEXT PRIMARY KEY, status TEXT NOT NULL, amount_zat TEXT NOT NULL, "
                "payment_uri TEXT NOT NULL, address TEXT NOT NULL, seq INTEGER NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "invoice_id TEXT NOT NULL, event_id TEXT NOT NULL, "
                "PRIMARY KEY (invoice_id, event_id))"
            )
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(invoices)")}
            if "updated_at" not in columns:
                # Files made before invoices were pruned: start their clock now.
                self._db.execute("ALTER TABLE invoices ADD COLUMN updated_at REAL")
                self._db.execute("UPDATE invoices SET updated_at = ?", (time.time(),))

    def add(self, invoice_id: str, amount_zat, payment_uri: str, address: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO invoices "
                "(id, status, amount_zat, payment_uri, address, seq, updated_at) "
                "VALUES (?, 'pending', ?, ?, ?, -1, ?)",
                (invoice_id, json.dumps(amount_zat), payment_uri, address, time.time()),
            )
            self._db.execute("DELETE FROM events WHERE invoice_id = ?", (invoice_id,))

    def _row(self, invoice_id):
        if not isinstance(invoice_id, str):
            return None
        return self._db.execute(
            "SELECT status, amount_zat, payment_uri, address, seq FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()

    def get(self, invoice_id) -> dict | None:
        with self._lock:
            row = self._row(invoice_id)
        if row is None:
            return None
        return {
            "status": row[0],
            "amount_zat": json.loads(row[1]),
            "payment_uri": row[2],
            "address": row[3],
            "seq": row[4],
        }

    def is_paid(self, invoice_id) -> bool:
        record = self.get(invoice_id)
        return bool(record and record["status"] == "paid")

    def is_new_event(self, invoice_id: str, event_id: str, seq) -> bool:
        """True unless this event was already applied or is older than one that was."""
        with self._lock:
            row = self._row(invoice_id)
            if row is None:
                return False
            seen = self._db.execute(
                "SELECT 1 FROM events WHERE invoice_id = ? AND event_id = ?",
                (invoice_id, event_id),
            ).fetchone()
            if seen is not None:
                return False
            return not (isinstance(seq, int) and seq <= row[4])

    def record(self, invoice_id: str, event_id: str, seq, status: str) -> None:
        """Remember an event and move the status on. ``paid`` is final."""
        with self._lock, self._db:
            row = self._row(invoice_id)
            if row is None:
                return
            self._db.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?)", (invoice_id, event_id)
            )
            new_seq = max(row[4], seq) if isinstance(seq, int) else row[4]
            new_status = row[0] if row[0] == "paid" else status
            self._db.execute(
                "UPDATE invoices SET status = ?, seq = ?, updated_at = ? WHERE id = ?",
                (new_status, new_seq, time.time(), invoice_id),
            )

    def prune(self, max_age_secs: float, *, now: float | None = None) -> int:
        """Forget invoices untouched for ``max_age_secs``, and their events.

        Nothing in an invoice identifies a person, but there is no reason to keep
        old ones: fewer records means less to leak. Returns how many were removed.
        """
        cutoff = (time.time() if now is None else now) - max_age_secs
        with self._lock, self._db:
            old = [
                row[0]
                for row in self._db.execute(
                    "SELECT id FROM invoices WHERE updated_at < ?", (cutoff,)
                )
            ]
            for invoice_id in old:
                self._db.execute("DELETE FROM events WHERE invoice_id = ?", (invoice_id,))
                self._db.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        return len(old)

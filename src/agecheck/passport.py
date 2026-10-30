"""Shared pieces of the passport (ZKPassport) age check.

The proofs are checked by the passport service (``passport/`` in this repository), which
the site reaches server to server. This module holds what the site itself must get right:
a fresh scope for every check, a record of scopes already tried, and a client for the
service. It knows nothing about any particular website.
"""

import secrets
import sqlite3
import threading
import time

import requests

# Every scope starts with this; the passport service refuses any other.
SCOPE_PREFIX = "age-over-18:"


class PassportError(Exception):
    """The passport service could not be reached, or its answer made no sense."""


def new_scope():
    """A fresh, unguessable scope for one passport check."""
    return SCOPE_PREFIX + secrets.token_urlsafe(16)


class UsedScopes:
    """Scopes that have been tried, kept on the server.

    The session lives in the visitor's cookie, so taking the scope out of the session is not
    enough: a visitor who kept the old cookie could send it again. This records each scope as
    it is tried and refuses it after that. Entries older than a visit are dropped, since the
    session's own timestamp refuses those anyway.

    With a file path the record lives in a SQLite file, so a restart forgets nothing and
    processes sharing the file share the record. Without one (``None``) it lives in memory,
    which is what the tests use.
    """

    def __init__(self, keep_seconds, path=None):
        self.keep_seconds = keep_seconds
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False, timeout=10)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS used_scopes (scope TEXT PRIMARY KEY, used_at REAL)"
            )

    def claim(self, scope):
        """True the first time a scope is claimed, False after that."""
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM used_scopes WHERE used_at < ?", (now - self.keep_seconds,)
            )
            added = self._db.execute(
                "INSERT OR IGNORE INTO used_scopes (scope, used_at) VALUES (?, ?)", (scope, now)
            )
            return added.rowcount == 1

    def release(self, scope):
        """Give a scope back when its try never happened (the check was unreachable)."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM used_scopes WHERE scope = ?", (scope,))


class PassportChecker:
    """Client for the passport service: checks proofs and serves the browser script."""

    def __init__(self, base_url, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def check(self, proofs, result, domain, scope):
        """True only if the service says the proofs show 18 or over for this domain and scope."""
        try:
            response = requests.post(
                self.base_url + "/verify",
                json={"proofs": proofs, "result": result, "domain": domain, "scope": scope},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("ok") is True
        except (requests.RequestException, ValueError) as exc:
            raise PassportError(f"passport service unavailable: {type(exc).__name__}") from exc

    def client_js(self):
        """The browser side of the check, as served by the passport service."""
        try:
            response = requests.get(self.base_url + "/client.js", timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PassportError(f"passport service unavailable: {type(exc).__name__}") from exc
        return response.content

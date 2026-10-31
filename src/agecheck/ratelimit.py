"""A per-address rate limiter, shared by the age-gate site and the verification service."""

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time


class RateLimiter:
    """Allow `limit` requests per `window` seconds for each client address.

    With a file path the counts live in a SQLite file, so they survive a restart and
    every worker process that opens the same file shares them. Without one (``None``)
    they live in this process's memory, which is what the tests use. Behind a reverse
    proxy every visitor may share the proxy's address.

    Addresses are never stored: only an HMAC of each one under `secret`, so the file
    cannot be read back into addresses without the key (a plain hash could be, since
    there are only four billion IPv4 addresses to try). Workers must share the secret
    to share counts, so give them the same SECRET_KEY.
    """

    def __init__(self, limit, window=60.0, path=None, secret=None):
        self.limit = limit
        self.window = window
        self._secret = (secret or secrets.token_hex(32)).encode()
        self._lock = threading.Lock()
        # isolation_level=None: we open each transaction ourselves with BEGIN IMMEDIATE,
        # which makes other processes wait their turn instead of counting at the same time.
        self._db = sqlite3.connect(
            path or ":memory:", check_same_thread=False, timeout=10, isolation_level=None
        )
        with self._lock:
            # Overwrite deleted rows on disk instead of leaving them in free pages.
            self._db.execute("PRAGMA secure_delete = ON")
            self._db.execute("CREATE TABLE IF NOT EXISTS hits (key TEXT NOT NULL, at REAL NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS hits_by_key ON hits (key, at)")

    def allow(self, key):
        if self.limit <= 0:
            return True
        key = hmac.new(self._secret, str(key).encode(), hashlib.sha256).hexdigest()
        now = time.time()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute("DELETE FROM hits WHERE at <= ?", (now - self.window,))
                (count,) = self._db.execute(
                    "SELECT COUNT(*) FROM hits WHERE key = ?", (key,)
                ).fetchone()
                allowed = count < self.limit
                if allowed:
                    self._db.execute("INSERT INTO hits (key, at) VALUES (?, ?)", (key, now))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return allowed

    def reset(self):
        with self._lock:
            self._db.execute("DELETE FROM hits")

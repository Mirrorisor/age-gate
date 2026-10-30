import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from urllib.parse import urlsplit

import requests

from flask import Flask, g, session, redirect, url_for, request, jsonify

from agecheck import AgeVerifier, VerifierError
from agecheck.passport import PassportChecker, PassportError, UsedScopes, new_scope
from agecheck.reasons import explain
from agecheck.zecpay import (
    InvoiceStore,
    PaymentError,
    ZecCheckoutClient,
    verify_webhook,
)

VERIFIER = os.environ.get("VERIFIER_URL", "http://127.0.0.1:8000")
SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "http://localhost:5000")
# Demo mode uses a fake test wallet. Never enable it on a public site.
DEMO = os.environ.get("DEMO_FAKE_WALLET") == "1"

app = Flask(__name__)
# The session cookie is signed with this key, so anyone who knows it can forge a
# "passed the age check" cookie. With no SECRET_KEY we make a random one for this
# run (nobody can guess it, but everyone is logged out when the site restarts).
_PLACEHOLDER_KEY = "change-me-later"
_configured_key = os.environ.get("SECRET_KEY", "")
HAVE_REAL_KEY = bool(_configured_key) and _configured_key != _PLACEHOLDER_KEY
app.secret_key = _configured_key if HAVE_REAL_KEY else secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set SESSION_COOKIE_SECURE=1 when the site is served over https.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,  # the default for every route but the proof upload
)
# Behind a tunnel or reverse proxy every request arrives from the proxy, so the rate
# limiter would count all visitors as one. TRUST_PROXY=1 reads the visitor's address
# from the proxy's X-Forwarded-For header instead. Only set it when the site is reachable
# through that one proxy and nothing else, or visitors could fake the header.
def trust_one_proxy(flask_app):
    from werkzeug.middleware.proxy_fix import ProxyFix

    flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1)


if os.environ.get("TRUST_PROXY") == "1":
    trust_one_proxy(app)
# The wallet's zero-knowledge proof is hundreds of kilobytes, so /api/finish gets more room.
PROOF_UPLOAD_LIMIT = 4 * 1024 * 1024
verifier = AgeVerifier(VERIFIER)

# Optional: prove age with a passport through the ZKPassport app. PASSPORT_URL is the
# passport service (passport/ in this repo), reached server to server; empty turns it off.
PASSPORT_URL = os.environ.get("PASSPORT_URL", "").rstrip("/")
# A passport proof is several zero-knowledge proofs, so its upload gets more room.
PASSPORT_UPLOAD_LIMIT = 8 * 1024 * 1024


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


# Requests per minute per address for the age-check and payment routes. 0 turns it off.
limiter = RateLimiter(
    int(os.environ.get("RATE_LIMIT_PER_MIN", "30")),
    path=os.environ.get("RATE_LIMIT_DB") or None,
    secret=app.secret_key,
)


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "too large", "message": "That request was too large."}), 413


def too_many():
    response = jsonify({"error": "too many requests", "message": "Too many tries. Wait a minute."})
    response.status_code = 429
    response.headers["Retry-After"] = "60"
    return response


@app.before_request
def throttle():
    g.nonce = secrets.token_urlsafe(16)
    if request.path == "/api/finish":
        request.max_content_length = PROOF_UPLOAD_LIMIT
    if request.path == "/api/passport/finish":
        request.max_content_length = PASSPORT_UPLOAD_LIMIT
    if request.path in (
        "/api/start", "/api/finish", "/api/passport/start", "/api/passport/finish", "/pay",
        "/demo-verify",
    ):
        if not limiter.allow(request.remote_addr):
            return too_many()


@app.after_request
def add_security_headers(response):
    nonce = getattr(g, "nonce", "")
    # The two inline scripts in this file get the per-request nonce the policy allows.
    if response.mimetype == "text/html" and not response.direct_passthrough:
        body = response.get_data(as_text=True)
        if "<script>" in body:
            response.set_data(body.replace("<script>", '<script nonce="' + nonce + '">'))
    # The passport page talks to the ZKPassport app through ZKPassport's WebSocket relay,
    # so only that page may open WebSocket connections to other hosts.
    connect = "'self' wss:" if request.path == "/passport" else "'self'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'nonce-" + nonce + "'; connect-src " + connect + "; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path in ("/pay", "/pay/status", "/members") or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

# Optional payment step after the age check. Off by default. Test network only.
PAYMENT_GATE = os.environ.get("PAYMENT_GATE") == "1"
ZC_URL = os.environ.get("ZC_URL", "http://127.0.0.1:8080")
ZC_API_KEY = os.environ.get("ZC_API_KEY", "")
ZC_WEBHOOK_SECRET = os.environ.get("ZC_WEBHOOK_SECRET", "")
PRICE_ZEC = os.environ.get("PRICE_ZEC", "0.001")
if PAYMENT_GATE and (len(ZC_API_KEY) < 24 or len(ZC_WEBHOOK_SECRET) < 24):
    raise RuntimeError("PAYMENT_GATE needs ZC_API_KEY and ZC_WEBHOOK_SECRET (24+ characters each)")
if PAYMENT_GATE and not HAVE_REAL_KEY:
    raise RuntimeError("PAYMENT_GATE needs a real SECRET_KEY (see .env.example)")
zec = ZecCheckoutClient(ZC_URL, ZC_API_KEY)
invoices = InvoiceStore(os.environ.get("INVOICE_DB", "invoices.db") if PAYMENT_GATE else None)
# Invoices untouched for this many days are deleted (0 keeps them forever).
INVOICE_RETENTION_DAYS = float(os.environ.get("INVOICE_RETENTION_DAYS", "30"))

PAGE = """
<h1>Verify your age</h1>
<p>Your wallet will prove you are over 18 without sharing your birthdate.</p>
<button id="go">Verify with my wallet</button>
<p id="msg"></p>
<script>
async function go() {
  const msg = document.getElementById('msg');
  try {
    if (!('DigitalCredential' in window)) {
      msg.textContent = 'This browser does not support the Digital Credentials API.';
      return;
    }
    msg.textContent = 'Starting...';
    const start = await fetch('/api/start', {method: 'POST'});
    if (!start.ok) throw new Error('Could not start a session');
    const req = await start.json();
    const cred = await navigator.credentials.get(req);
    const response = (cred.data && cred.data.response) ? cred.data.response : cred.data;
    const fin = await fetch('/api/finish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({response: response})
    });
    const out = await fin.json();
    if (out.ok) { location.href = '/members'; }
    else { msg.textContent = out.message || ('Not verified: ' + JSON.stringify(out.detail)); }
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
  }
}
document.getElementById('go').addEventListener('click', go);
</script>
"""


@app.route("/")
def home():
    return """
    <h1>Welcome</h1>
    <p>This site is for adults only.</p>
    <a href="/verify">Verify my age</a>
    """


@app.route("/verify")
def verify():
    extra = ""
    if PASSPORT_URL:
        extra += '<hr><p><a href="/passport">Or use your passport (ZKPassport app)</a></p>'
    if DEMO:
        extra += '<hr><p><a href="/demo-verify">Demo mode: use the fake test wallet</a></p>'
    return PAGE + extra


@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        started = verifier.start_session()
    except VerifierError:
        return jsonify({"error": "verifier unavailable"}), 502
    session["av_session"] = started["session_id"]
    return jsonify(started["offer"])


@app.route("/api/finish", methods=["POST"])
def api_finish():
    sid = session.get("av_session")
    if not sid:
        return jsonify({
            "ok": False,
            "detail": "no session",
            "message": "Your check expired. Reload the page and try again.",
        }), 400
    body = request.get_json(silent=True) or {}
    try:
        ok, detail = verifier.finish(sid, body.get("response"))
    except VerifierError:
        return jsonify({
            "ok": False,
            "detail": "verifier unavailable",
            "message": "The age-check service is not reachable right now. Try again later.",
        }), 502
    session.pop("av_session", None)
    if ok:
        session["is_adult"] = True
    payload = {"ok": ok, "detail": detail}
    if not ok:
        payload["message"] = explain(detail)
    return jsonify(payload)


PASSPORT_PAGE = """
<h1>Use your passport</h1>
<p>The ZKPassport app reads your passport's chip and proves you are 18 or over.
This site learns only that, not your name, birthdate, nationality or passport number.</p>
<div id="passport" data-dev="{dev}" data-start="/api/passport/start" data-finish="/api/passport/finish">
<button id="passport-go">Start</button>
<p id="passport-msg"></p>
<div id="passport-qr"></div>
<p><a id="passport-link" hidden>Open the ZKPassport app</a></p>
<details id="passport-test" hidden><summary>Test mode: the request link</summary>
<textarea id="passport-url" readonly rows="6" cols="60"></textarea></details>
</div>
<p><a href="/verify">Back</a></p>
<script type="module" nonce="{nonce}" src="/passport/client.js"></script>
"""
_passport_client = {}

# How long a passport visit's scope stays usable after the page was opened.
PASSPORT_VISIT_SECONDS = 15 * 60


used_scopes = UsedScopes(PASSPORT_VISIT_SECONDS, os.environ.get("PASSPORT_SCOPES_DB") or None)


def passport_check(proofs, result, domain, scope):
    """Ask the passport service whether the proofs show 18 or over. True or False."""
    return PassportChecker(PASSPORT_URL).check(proofs, result, domain, scope)


@app.route("/passport")
def passport_page():
    if not PASSPORT_URL:
        return "Passports are not set up on this site.", 404
    dev = "1" if os.environ.get("PASSPORT_DEV_MODE", "1") == "1" else "0"
    return PASSPORT_PAGE.replace("{dev}", dev).replace("{nonce}", g.nonce)


@app.route("/api/passport/start", methods=["POST"])
def passport_start():
    """Start a passport check: a fresh scope, which the proofs will be made for.

    Done on Start, not on page load, so just visiting /passport sets no cookie. A proof
    captured in one check is refused in any other, and each scope can be tried once (see
    UsedScopes), within PASSPORT_VISIT_SECONDS.
    """
    if not PASSPORT_URL:
        return jsonify({"error": "not found"}), 404
    scope = new_scope()
    session["passport_scope"] = scope
    session["passport_scope_at"] = time.time()
    return jsonify({"scope": scope})


@app.route("/passport/client.js")
def passport_client():
    if not PASSPORT_URL:
        return "Not found", 404
    if "js" not in _passport_client:
        try:
            response = requests.get(PASSPORT_URL + "/client.js", timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return "Passport service unavailable", 502
        _passport_client["js"] = response.content
    return app.response_class(_passport_client["js"], mimetype="text/javascript")


@app.route("/api/passport/finish", methods=["POST"])
def passport_finish():
    if not PASSPORT_URL:
        return jsonify({"ok": False, "message": "Passports are not set up on this site."}), 404
    body = request.get_json(silent=True) or {}
    domain = urlsplit(SITE_ORIGIN).hostname or "localhost"
    scope = session.get("passport_scope")
    age = time.time() - session.get("passport_scope_at", 0)
    if not scope or age > PASSPORT_VISIT_SECONDS or not used_scopes.claim(scope):
        return jsonify({
            "ok": False,
            "message": "Your check expired. Reload the page and try again.",
        }), 400
    try:
        ok = passport_check(body.get("proofs"), body.get("result"), domain, scope)
    except (PassportError, requests.RequestException, ValueError):
        used_scopes.release(scope)  # the check never ran, so the visit keeps its try
        return jsonify({
            "ok": False,
            "message": "The passport check is not reachable right now. Try again later.",
        }), 502
    session.pop("passport_scope", None)
    session.pop("passport_scope_at", None)
    if not ok:
        return jsonify({"ok": False, "message": "The passport proof did not show you are 18 or over."})
    session["is_adult"] = True
    return jsonify({"ok": True, "next": url_for("members")})


@app.route("/demo-verify")
def demo_verify():
    if not DEMO:
        return "Demo mode is off.", 404
    # 1. Ask the verifier for a session, like a real site would.
    try:
        started = verifier.start_session()
    except VerifierError:
        return "<h1>Verifier unavailable</h1>", 502
    # 2. The fake wallet (running inside the verifier's container) answers.
    job = json.dumps({"request": started["offer"], "origin": SITE_ORIGIN})
    p = subprocess.run(
        ["docker", "exec", "-i", "zkv", "/app/.venv/bin/python", "/tmp/work/wallet_present.py"],
        input=job, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if p.returncode != 0:
        return "<h1>Fake wallet failed</h1><pre>" + html.escape(p.stderr[-3000:]) + "</pre>", 500
    wallet = json.loads(p.stdout)
    # 3. Send the answer to the verifier and act only on its verdict.
    try:
        ok, detail = verifier.finish(started["session_id"], wallet["response"])
    except VerifierError:
        return "<h1>Verifier unavailable</h1>", 502
    if ok:
        session["is_adult"] = True
        return redirect(url_for("members"))
    return (
        "<h1>Not verified</h1><p>" + html.escape(explain(detail)) + "</p><pre>"
        + html.escape(json.dumps(detail, indent=2)) + "</pre>"
    ), 403


PAY_TAIL = """
<p id="status">Waiting for payment...</p>
<script>
async function poll() {
  try {
    const r = await fetch('/pay/status');
    const s = await r.json();
    document.getElementById('status').textContent = 'Status: ' + s.status;
    if (s.status === 'paid') { location.href = '/members'; return; }
  } catch (e) {}
  setTimeout(poll, 5000);
}
poll();
</script>
"""


@app.route("/pay")
def pay():
    if not session.get("is_adult"):
        return redirect(url_for("verify"))
    if not PAYMENT_GATE:
        return redirect(url_for("members"))
    if INVOICE_RETENTION_DAYS > 0:
        invoices.prune(INVOICE_RETENTION_DAYS * 86400)
    record = invoices.get(session.get("invoice_id"))
    if record is None or record["status"] == "expired":
        try:
            created = zec.create_invoice(PRICE_ZEC, secrets.token_hex(8))
        except PaymentError:
            return "<h1>Payment service unavailable</h1>", 502
        invoices.add(
            created["id"],
            created.get("amount_zat"),
            str(created.get("payment_uri", "")),
            str(created.get("address", "")),
        )
        session["invoice_id"] = created["id"]
        record = invoices.get(created["id"])
    if record["status"] == "paid":
        return redirect(url_for("members"))
    link = ""
    if record["payment_uri"].startswith("zcash:"):
        link = '<p><a href="' + html.escape(record["payment_uri"], quote=True) + '">Open in my wallet</a></p>'
    return (
        "<h1>Payment</h1>"
        "<p>You passed the age check. This area needs a small shielded Zcash payment "
        "(test network only).</p>"
        "<p>Amount: " + html.escape(PRICE_ZEC) + " ZEC</p>"
        "<p>Address:<br><code>" + html.escape(record["address"]) + "</code></p>"
        + link
        + "<p>Pay from a shielded balance. A payment from a transparent balance puts "
        "its time and amount on the public chain.</p>"
        + PAY_TAIL
    )


@app.route("/pay/status")
def pay_status():
    record = invoices.get(session.get("invoice_id"))
    return jsonify({"status": record["status"] if record else "none"})


@app.route("/webhooks/zeccheckout", methods=["POST"])
def zeccheckout_webhook():
    raw = request.get_data()
    if not verify_webhook(ZC_WEBHOOK_SECRET, request.headers.get("ZecCheckout-Signature"), raw):
        return jsonify({"error": "bad signature"}), 400
    body = request.get_json(silent=True)
    invoice = body.get("invoice") if isinstance(body, dict) else None
    if not isinstance(invoice, dict):
        return jsonify({"error": "bad body"}), 400
    event_id, seq, event = body.get("event_id"), body.get("seq"), body.get("event")
    invoice_id, status = invoice.get("id"), invoice.get("status")
    if not all(isinstance(v, str) for v in (event_id, event, invoice_id, status)):
        return jsonify({"error": "bad body"}), 400
    if not invoices.is_new_event(invoice_id, event_id, seq):
        return jsonify({"ignored": True})
    if status == "paid":
        record = invoices.get(invoice_id)
        try:
            confirmed_by_server = zec.get_invoice(invoice_id)
        except PaymentError:
            return jsonify({"error": "could not confirm"}), 503  # the sender will retry
        expected = record["amount_zat"]
        amount_ok = True
        if isinstance(expected, int):
            confirmed = invoice.get("confirmed_zat")
            amount_ok = (
                invoice.get("amount_zat") == expected
                and isinstance(confirmed, int)
                and confirmed >= expected
            )
        if confirmed_by_server.get("status") != "paid" or not amount_ok:
            return jsonify({"ignored": True})
        invoices.record(invoice_id, event_id, seq, "paid")
        return jsonify({"ok": True})
    if status in ("pending", "underpaid", "detected", "expired"):
        invoices.record(invoice_id, event_id, seq, status)
        return jsonify({"ok": True})
    return jsonify({"ignored": True})


@app.route("/members")
def members():
    if not session.get("is_adult"):
        return redirect(url_for("home"))
    if PAYMENT_GATE and not invoices.is_paid(session.get("invoice_id")):
        return redirect(url_for("pay"))
    return '<h1>Members area</h1><p>You passed the age check.</p><p><a href="/privacy">What this site learns</a> | <a href="/logout">Log out</a></p>'


@app.route("/privacy")
def privacy():
    payment = (
        "<li>Payment step: the checkout service tells this site whether an invoice "
        "was paid. Shielded Zcash payments do not reveal who paid.</li>"
        if PAYMENT_GATE
        else ""
    )
    passport = (
        "<li>Passport check: the ZKPassport app on your phone proves you are 18 or over. "
        "This site sees the answer, not your name, birthdate, nationality or passport "
        "number, and drops the identifier ZKPassport proofs carry, so two visits cannot be "
        "linked. The app and this page talk through ZKPassport's relay service. When you "
        "press Start, the cookie also holds a random code for that check, removed when it "
        "finishes.</li>"
        if PASSPORT_URL
        else ""
    )
    return (
        "<h1>What this site learns about you</h1>"
        "<p>This is an experimental demo. It uses test certificates and must not be "
        "used to protect real people or content.</p>"
        "<ul>"
        "<li>Age check: your wallet proves you are over 18 using a zero-knowledge proof. "
        "This site and the verifier see the answer (yes or no), not your birthdate, "
        "name or ID.</li>"
        "<li>To check the proof, the verifier sees which organisation issued your "
        "credential (its signing certificate), so it learns, for example, the country "
        "or state. It does not keep this when the check passes.</li>"
        "<li>A browser cookie records that you passed (and, if payments are on, which "
        "random invoice number is yours). It holds no personal details. Logging out "
        "clears it completely.</li>"
        + payment
        + passport
        + "<li>This demo keeps no accounts and no record of who you are.</li>"
        "</ul>"
        '<p><a href="/">Home</a></p>'
    )


@app.route("/logout")
def logout():
    # Forget everything the cookie held, not just the pass. Keeping the invoice
    # number would hand a paid invoice to the next person on a shared browser and
    # tie their visit to the previous one.
    session.clear()
    return redirect(url_for("home"))


@app.route("/health")
def health():
    try:
        info = verifier.health()
    except VerifierError:
        return "<h1>Verifier is down</h1><p>The age-check service is not reachable.</p>", 503
    version = html.escape(str(info.get("zk_age_verifier", "unknown")))
    return "<h1>Verifier is up</h1><p>Version: " + version + "</p>"

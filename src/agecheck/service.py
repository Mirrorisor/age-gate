"""A standalone age-verification service, for sites that are not written in Python (roadmap M8).

The site runs this next to itself and never handles proofs. The flow:

1. The site makes a one-time code (a nonce), remembers it for this visitor, and sends them to
   ``<service>/start?nonce=<nonce>``.
2. The service runs the age check: a passport (ZKPassport) or a phone wallet (zk-age-verifier),
   using the same gates as the age-gate site.
3. On a pass the service sends the visitor to the site's callback, ``CALLBACK_URL?token=<token>``,
   with a token signed with the secret the two share (``agecheck.handoff``).
4. The site checks the token: signature, expiry, its own origin, and its own nonce, which it then
   forgets. See ``examples/node-site/server.js`` for a check in about twenty lines.

The service only ever redirects to the one configured ``CALLBACK_URL``, so it cannot be used to
send visitors anywhere else, and it keeps nothing after the handoff: the session is cleared.

Settings (environment variables):

    CALLBACK_URL        the site's callback, e.g. https://example.com/age-callback (required)
    SERVICE_SECRET      the secret shared with the site, 32+ characters (required)
    SERVICE_DOMAIN      this service's host name as visitors' browsers see it (for passports)
    PASSPORT_URL        the passport service (passport/ in this repository); empty turns it off
    VERIFIER_URL        the zk-age-verifier service; empty turns the phone-wallet route off
    PASSPORT_DEV_MODE   1 (default) for mock passports only
    SCOPES_DB, RATE_LIMIT_DB   SQLite files, so restarts and several workers share state
    RATE_LIMIT_PER_MIN  per address, default 30; SESSION_COOKIE_SECURE=1 behind https;
    TRUST_PROXY=1       read the visitor's address from the one proxy in front

Run it with: gunicorn "agecheck.service:create_app()"
"""

import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

from flask import Flask, redirect, request, session

from agecheck.flask_gate import AgeGate
from agecheck.flask_passport import PassportGate
from agecheck.handoff import issue
from agecheck.ratelimit import RateLimiter

_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_NONCE_KEY = "handoff_nonce"
_PASS_KEY = "is_adult"


def _origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def create_app(config=None):
    """Build the service. ``config`` overrides the environment variables (used by the tests)."""
    env = {**os.environ, **(config or {})}
    callback = env.get("CALLBACK_URL", "")
    secret = env.get("SERVICE_SECRET", "")
    if urlsplit(callback).scheme not in ("http", "https") or not urlsplit(callback).netloc:
        raise RuntimeError("CALLBACK_URL must be the site's full callback URL")
    if len(secret) < 32:
        raise RuntimeError("SERVICE_SECRET must be at least 32 characters")
    passport_url = env.get("PASSPORT_URL", "").rstrip("/")
    verifier_url = env.get("VERIFIER_URL", "").rstrip("/")
    if not passport_url and not verifier_url:
        raise RuntimeError("set PASSPORT_URL or VERIFIER_URL (or both)")

    app = Flask(__name__)
    # The service's own session cookie only carries the nonce and the pass between the check and
    # the handoff, so a key made fresh for this process is enough; set one to share across workers.
    app.secret_key = env.get("SERVICE_SESSION_KEY") or secrets.token_hex(32)
    app.config.update(
        # Its own name, so it never collides with the site's cookie when both share a host.
        SESSION_COOKIE_NAME="agecheck_service",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env.get("SESSION_COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,  # passport proofs are several megabytes at most
    )
    if env.get("TRUST_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    limiter = RateLimiter(int(env.get("RATE_LIMIT_PER_MIN", "30")),
                          path=env.get("RATE_LIMIT_DB") or None, secret=app.secret_key)

    methods = []
    if passport_url:
        passport = PassportGate(
            passport_url, domain=env.get("SERVICE_DOMAIN", "localhost"), url_prefix="/passport",
            default_next="/handoff", session_key=_PASS_KEY,
            dev_mode=env.get("PASSPORT_DEV_MODE", "1") == "1",
            scopes_db=env.get("SCOPES_DB") or None,
        )
        app.register_blueprint(passport.blueprint)
        methods.append(("/passport/verify", "Use your passport (ZKPassport app)"))
    if verifier_url:
        wallet = AgeGate(verifier_url, url_prefix="/wallet", default_next="/handoff",
                         session_key=_PASS_KEY)
        app.register_blueprint(wallet.blueprint)
        methods.append(("/wallet/verify", "Use a phone wallet"))

    @app.before_request
    def throttle():
        if request.method == "POST" or request.path in ("/start", "/handoff"):
            if not limiter.allow(request.remote_addr):
                return "Too many tries. Wait a minute.", 429
        return None

    @app.route("/start")
    def start():
        nonce = request.args.get("nonce", "")
        if not _NONCE.match(nonce):
            return "<h1>Bad request</h1><p>Start again from the site.</p>", 400
        session.clear()  # a new check never inherits an earlier pass
        session[_NONCE_KEY] = nonce
        if len(methods) == 1:
            return redirect(methods[0][0])
        return redirect("/choose")

    @app.route("/choose")
    def choose():
        links = "".join(f'<p><a href="{path}">{label}</a></p>' for path, label in methods)
        return "<h1>Prove you are 18 or over</h1>" + links

    @app.route("/handoff")
    def handoff():
        nonce = session.get(_NONCE_KEY)
        passed = session.get(_PASS_KEY) is True
        session.clear()  # one token per check; nothing kept afterwards
        if not nonce or not passed:
            return "<h1>Not verified</h1><p>Start again from the site.</p>", 400
        token = issue(secret, nonce, _origin(callback))
        joiner = "&" if urlsplit(callback).query else "?"
        return redirect(callback + joiner + urlencode({"token": token}))

    @app.after_request
    def headers(response):
        # Only this service's own script files run. The passport page also talks to ZKPassport's
        # relay over a WebSocket; nothing else may connect anywhere.
        connect = "'self' wss:" if request.path == "/passport/verify" else "'self'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; connect-src " + connect + "; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # The handoff URL carries the token: never send it on to anyone in a Referer header.
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    return app

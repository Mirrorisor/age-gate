"""A drop-in "prove you are over 18 with your passport" gate for Flask sites.

Usage::

    from flask import Flask
    from agecheck.flask_passport import PassportGate

    app = Flask(__name__)
    app.secret_key = "a long random string"
    gate = PassportGate("http://127.0.0.1:8100", domain="example.com")  # the passport service
    app.register_blueprint(gate.blueprint)

    @app.route("/members")
    @gate.age_required
    def members():
        return "Adults only"

A visitor who has not passed is sent to ``/passport-check/verify``. Pressing Start shows a
QR code for the ZKPassport app, which proves "18 or over" from the passport's chip; the
passport service (``passport/`` in this repository) checks the proofs. The site learns only
"18 or over: yes" and keeps a flag in the signed session cookie, the same one
``agecheck.flask_gate.AgeGate`` uses, so a site can offer both.

Each check gets its own random scope, made when the visitor presses Start (so just opening
the page sets no cookie) and accepted once, within ``visit_seconds``. A proof captured from
one check is refused in any other.

The page loads one module script from this site and talks to ZKPassport's relay over a
WebSocket, so the host's Content-Security-Policy must allow ``connect-src 'self' wss:`` on
the verify page. Rate limiting, https and a real ``SECRET_KEY`` are the host site's job.
``dev_mode=True`` (the default) is for mock passports only; see passport/README.md.
"""

import html
import time

from flask import Blueprint, Response, jsonify, request, session, url_for

from agecheck.flask_gate import Gate
from agecheck.passport import PassportChecker, PassportError, UsedScopes, new_scope


class PassportGate(Gate):
    """A passport-check blueprint plus an ``age_required`` decorator.

    Args:
        passport_url: Base URL of the passport service. Give this or ``checker``.
        checker: An object with ``check(proofs, result, domain, scope)`` and ``client_js()``,
            for tests or a custom client. Give this or ``passport_url``.
        domain: This site's host name as visitors' browsers see it (no scheme, no path).
            Proofs are made for it, and proofs made for any other domain are refused.
        url_prefix: Where the gate's routes live (default ``/passport-check``).
        default_next: Where to send a visitor after passing, when they came straight
            to the gate rather than from a protected page. Must be a path on this site.
        session_key: The session key that records a pass.
        dev_mode: Ask for mock passports (the default). Real passports need ``False``,
            and an outside review first.
        scopes_db: A SQLite file for the record of scopes already tried, so a restart
            cannot give a used check a second try. ``None`` keeps it in memory.
        visit_seconds: How long a started check stays usable.
    """

    verify_endpoint = "agecheck_passport.verify_page"

    def __init__(self, passport_url=None, *, checker=None, domain, url_prefix="/passport-check",
                 default_next="/", session_key="is_adult", dev_mode=True, scopes_db=None,
                 visit_seconds=15 * 60):
        if (passport_url is None) == (checker is None):
            raise ValueError("give exactly one of passport_url or checker")
        if not domain or "/" in domain or ":" in domain:
            raise ValueError("domain is a bare host name, such as example.com")
        super().__init__(default_next=default_next, session_key=session_key)
        self.checker = checker if checker is not None else PassportChecker(passport_url)
        self.domain = domain
        self.dev_mode = dev_mode
        self.visit_seconds = visit_seconds
        self.used_scopes = UsedScopes(visit_seconds, scopes_db)
        self._scope_key = session_key + "_passport_scope"
        self._scope_at_key = session_key + "_passport_scope_at"
        self._client_js = None
        self.blueprint = Blueprint("agecheck_passport", __name__, url_prefix=url_prefix)
        self._add_routes()

    def _add_routes(self):
        bp = self.blueprint

        def attr(endpoint):
            return html.escape(url_for(endpoint), quote=True)

        @bp.route("/verify")
        def verify_page():
            return (
                "<h1>Use your passport</h1>"
                "<p>The ZKPassport app reads your passport's chip and proves you are 18 or over. "
                "This site learns only that, not your name, birthdate, nationality or passport "
                "number.</p>"
                '<div id="passport" data-dev="' + ("1" if self.dev_mode else "0") + '"'
                ' data-start="' + attr("agecheck_passport.start") + '"'
                ' data-finish="' + attr("agecheck_passport.finish") + '">'
                '<button id="passport-go">Start</button>'
                '<p id="passport-msg"></p>'
                '<div id="passport-qr"></div>'
                '<p><a id="passport-link" hidden>Open the ZKPassport app</a></p>'
                '<details id="passport-test" hidden><summary>Test mode: the request link'
                '</summary><textarea id="passport-url" readonly rows="6" cols="60"></textarea>'
                "</details></div>"
                '<script type="module" src="' + attr("agecheck_passport.client") + '"></script>'
            )

        @bp.route("/client.js")
        def client():
            if self._client_js is None:
                try:
                    self._client_js = self.checker.client_js()
                except PassportError:
                    return Response("Passport service unavailable", status=502)
            return Response(self._client_js, mimetype="text/javascript")

        @bp.route("/start", methods=["POST"])
        def start():
            scope = new_scope()
            session[self._scope_key] = scope
            session[self._scope_at_key] = time.time()
            return jsonify({"scope": scope})

        @bp.route("/finish", methods=["POST"])
        def finish():
            scope = session.get(self._scope_key)
            age = time.time() - session.get(self._scope_at_key, 0)
            if not scope or age > self.visit_seconds or not self.used_scopes.claim(scope):
                return jsonify({
                    "ok": False,
                    "message": "Your check expired. Reload the page and try again.",
                }), 400
            body = request.get_json(silent=True) or {}
            try:
                ok = self.checker.check(body.get("proofs"), body.get("result"), self.domain, scope)
            except PassportError:
                self.used_scopes.release(scope)  # the check never ran, so the visit keeps its try
                return jsonify({
                    "ok": False,
                    "message": "The passport check is not reachable right now. Try again later.",
                }), 502
            session.pop(self._scope_key, None)
            session.pop(self._scope_at_key, None)
            if not ok:
                return jsonify({
                    "ok": False,
                    "message": "The passport proof did not show you are 18 or over.",
                })
            return jsonify({"ok": True, "next": self._passed()})

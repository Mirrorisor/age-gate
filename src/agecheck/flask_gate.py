"""A drop-in "prove you are over 18" gate for Flask sites.

Usage::

    from flask import Flask
    from agecheck.flask_gate import AgeGate

    app = Flask(__name__)
    app.secret_key = "a long random string"
    gate = AgeGate("http://127.0.0.1:8000")      # the zk-age-verifier service
    app.register_blueprint(gate.blueprint)

    @app.route("/members")
    @gate.age_required
    def members():
        return "Adults only"

A visitor who has not passed is sent to ``/age/verify``, whose button asks their
wallet for a zero-knowledge proof. The site learns only "over 18: yes" and keeps a
flag in the signed session cookie. The page has no inline script, so it works under
a strict Content-Security-Policy (``script-src 'self'``).

This module needs Flask (``pip install flask``); the rest of ``agecheck`` does not.
Rate limiting, https and a real ``SECRET_KEY`` are the host site's job.
"""

import html
from functools import wraps

from flask import Blueprint, Response, jsonify, redirect, request, session, url_for

from agecheck import AgeVerifier, VerifierError
from agecheck.reasons import explain

_SCRIPT = """\
async function go() {
  const button = document.getElementById('agecheck-go');
  const msg = document.getElementById('agecheck-msg');
  try {
    if (!('DigitalCredential' in window)) {
      msg.textContent = 'This browser does not support the Digital Credentials API.';
      return;
    }
    msg.textContent = 'Starting...';
    const start = await fetch(button.dataset.start, {method: 'POST'});
    if (!start.ok) throw new Error('Could not start a session');
    const offer = await start.json();
    const cred = await navigator.credentials.get(offer);
    const response = (cred.data && cred.data.response) ? cred.data.response : cred.data;
    const finish = await fetch(button.dataset.finish, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({response: response})
    });
    const out = await finish.json();
    if (out.ok) { location.href = out.next; }
    else { msg.textContent = out.message || 'Not verified.'; }
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
  }
}
document.getElementById('agecheck-go').addEventListener('click', go);
"""


class AgeGate:
    """An age-check blueprint plus an ``age_required`` decorator.

    Args:
        verifier_url: Base URL of the zk-age-verifier service. Give this or ``verifier``.
        verifier: An object with ``start_session()`` and ``finish(session_id, response)``,
            for tests or a custom client. Give this or ``verifier_url``.
        url_prefix: Where the gate's routes live (default ``/age``).
        default_next: Where to send a visitor after passing, when they came straight
            to the gate rather than from a protected page. Must be a path on this site.
        session_key: The session key that records a pass.
    """

    def __init__(self, verifier_url=None, *, verifier=None, url_prefix="/age",
                 default_next="/", session_key="is_adult"):
        if (verifier_url is None) == (verifier is None):
            raise ValueError("give exactly one of verifier_url or verifier")
        self.verifier = verifier if verifier is not None else AgeVerifier(verifier_url)
        self.default_next = default_next
        self.session_key = session_key
        self._pending_key = session_key + "_next"
        self._session_id_key = session_key + "_session"
        self.blueprint = Blueprint("agecheck_gate", __name__, url_prefix=url_prefix)
        self._add_routes()

    # ---- helpers for the host site -------------------------------------

    def is_adult(self):
        """True if this visitor has passed the check."""
        return bool(session.get(self.session_key))

    def revoke(self):
        """Forget that this visitor passed (log them out of the gate)."""
        session.pop(self.session_key, None)

    def age_required(self, view):
        """Protect a view: visitors who have not passed are sent to the gate."""

        @wraps(view)
        def wrapper(*args, **kwargs):
            if not self.is_adult():
                target = request.path
                if request.query_string:
                    target += "?" + request.query_string.decode("latin-1")
                session[self._pending_key] = target
                return redirect(url_for("agecheck_gate.verify_page"))
            return view(*args, **kwargs)

        return wrapper

    # ---- routes ----------------------------------------------------------

    def _safe_next(self, value):
        """Only ever redirect to a path on this site, never to another site."""
        if (
            isinstance(value, str)
            and value.startswith("/")
            and not value.startswith(("//", "/\\"))
            and "\n" not in value
            and "\r" not in value
        ):
            return value
        return self.default_next

    def _add_routes(self):
        bp = self.blueprint

        @bp.route("/verify")
        def verify_page():
            return (
                "<h1>Verify your age</h1>"
                "<p>Your wallet will prove you are over 18 without sharing your birthdate.</p>"
                '<button id="agecheck-go" data-start="'
                + html.escape(url_for("agecheck_gate.start"), quote=True)
                + '" data-finish="'
                + html.escape(url_for("agecheck_gate.finish"), quote=True)
                + '">Verify with my wallet</button>'
                '<p id="agecheck-msg"></p>'
                '<script src="'
                + html.escape(url_for("agecheck_gate.script"), quote=True)
                + '" defer></script>'
            )

        @bp.route("/verify.js")
        def script():
            return Response(_SCRIPT, mimetype="text/javascript")

        @bp.route("/start", methods=["POST"])
        def start():
            try:
                started = self.verifier.start_session()
            except VerifierError:
                return jsonify({"error": "verifier unavailable"}), 502
            session[self._session_id_key] = started["session_id"]
            return jsonify(started["offer"])

        @bp.route("/finish", methods=["POST"])
        def finish():
            sid = session.get(self._session_id_key)
            if not sid:
                return jsonify({
                    "ok": False,
                    "message": "Your check expired. Reload the page and try again.",
                }), 400
            body = request.get_json(silent=True) or {}
            try:
                ok, detail = self.verifier.finish(sid, body.get("response"))
            except VerifierError:
                return jsonify({
                    "ok": False,
                    "message": "The age-check service is not reachable right now. "
                               "Try again later.",
                }), 502
            session.pop(self._session_id_key, None)
            if not ok:
                return jsonify({"ok": False, "message": explain(detail)})
            session[self.session_key] = True
            target = self._safe_next(session.pop(self._pending_key, None))
            return jsonify({"ok": True, "next": target})

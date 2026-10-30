# Using the age gate in your own Flask site

`agecheck.flask_gate` adds a "prove you are over 18" step to any Flask site. It talks to a
running zk-age-verifier; see the README for how to start one. This is an experiment on test
certificates (see `docs/HARDENING.md` for what it does and does not protect).

```python
from flask import Flask
from agecheck.flask_gate import AgeGate

app = Flask(__name__)
app.secret_key = "a long random string"          # keep it secret and stable
gate = AgeGate("http://127.0.0.1:8000")          # the verifier's address
app.register_blueprint(gate.blueprint)

@app.route("/members")
@gate.age_required
def members():
    return "Adults only"
```

- A visitor who has not passed is sent to `/age/verify`, then back to the page they wanted.
- The page and its script have no inline code, so they work under a strict
  Content-Security-Policy such as `script-src 'self'`.
- The site learns "over 18: yes" and keeps one flag in the signed session cookie.
- `gate.is_adult()` and `gate.revoke()` are there for your own pages and logout route.
- Options: `url_prefix` (default `/age`), `default_next`, `session_key`.
- Not included, on purpose: rate limiting, https, security headers. Add those on your site
  (the age-gate site's `app.py` shows one way).
- Needs Flask (`pip install flask`). The rest of the `agecheck` package does not.

`examples/minimal_site.py` is a complete working site in about twenty lines.

## Adding the passport check

`agecheck.flask_passport.PassportGate` does the same with a passport, through the ZKPassport
app. It needs the passport service from `passport/` in this repository (see
[passport/README.md](../passport/README.md)).

```python
from agecheck.flask_passport import PassportGate

passport = PassportGate("http://127.0.0.1:8100", domain="example.com")
app.register_blueprint(passport.blueprint)
```

- Visitors who have not passed go to `/passport-check/verify`. Pressing Start shows a QR code
  for the app; the passport service checks the proofs.
- `domain` is your site's host name as visitors' browsers see it. Proofs are made for it, and
  proofs made for another domain are refused.
- Both gates use the same session flag by default, so a pass from either opens pages protected
  by either. `examples/passport_site.py` offers both.
- Each check has its own random scope, made when the visitor presses Start (opening the page
  sets no cookie) and accepted once within 15 minutes, so a captured proof cannot be replayed.
  Give `scopes_db` a file path to keep that record across restarts and shared by workers.
- The verify page talks to ZKPassport's relay over a WebSocket: if your site sends a
  Content-Security-Policy, allow `connect-src 'self' wss:` on that page.
- `dev_mode=True` (the default) asks for mock passports only. Keep it until the service has had
  an outside review.
- Options: `url_prefix` (default `/passport-check`), `default_next`, `session_key`,
  `dev_mode`, `scopes_db`, `visit_seconds`.

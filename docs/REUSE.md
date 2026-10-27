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

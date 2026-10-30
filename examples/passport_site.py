"""The smallest site that offers both age checks: a phone wallet or a passport.

Run it with a zk-age-verifier on port 8000 and the passport service on port 8100:

    SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
        flask --app examples/passport_site run

SITE_DOMAIN must be the host name visitors use (default localhost). The passport page
talks to ZKPassport's relay over a WebSocket, so a site with a Content-Security-Policy
must allow connect-src 'self' wss: on /passport-check/verify.
"""

import os

from flask import Flask

from agecheck.flask_gate import AgeGate
from agecheck.flask_passport import PassportGate

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
wallet = AgeGate(os.environ.get("VERIFIER_URL", "http://127.0.0.1:8000"))
passport = PassportGate(
    os.environ.get("PASSPORT_URL", "http://127.0.0.1:8100"),
    domain=os.environ.get("SITE_DOMAIN", "localhost"),
)
app.register_blueprint(wallet.blueprint)
app.register_blueprint(passport.blueprint)


@app.route("/")
def home():
    return (
        "<h1>Welcome</h1>"
        '<p><a href="/age/verify">Prove your age with a phone wallet</a></p>'
        '<p><a href="/passport-check/verify">Prove your age with a passport</a></p>'
        '<p><a href="/members">Members (adults only)</a></p>'
    )


@app.route("/members")
@wallet.age_required  # either gate's pass counts: they share one session flag
def members():
    return "<h1>Members area</h1><p>You passed the age check.</p>"

"""The smallest site that uses the age gate.

Run it with a zk-age-verifier on port 8000:

    SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
        flask --app examples/minimal_site run
"""

import os

from flask import Flask

from agecheck.flask_gate import AgeGate

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
gate = AgeGate(os.environ.get("VERIFIER_URL", "http://127.0.0.1:8000"))
app.register_blueprint(gate.blueprint)


@app.route("/")
def home():
    return '<h1>Welcome</h1><a href="/members">Members (adults only)</a>'


@app.route("/members")
@gate.age_required
def members():
    return "<h1>Members area</h1><p>You passed the age check.</p>"

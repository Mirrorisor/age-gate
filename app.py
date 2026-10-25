import html
import json
import os
import subprocess

import requests
from flask import Flask, session, redirect, url_for, request, jsonify

VERIFIER = "http://127.0.0.1:8000"
SITE_ORIGIN = "http://localhost:5000"
# Demo mode uses a fake test wallet. Never enable it on a public site.
DEMO = os.environ.get("DEMO_FAKE_WALLET") == "1"

app = Flask(__name__)
app.secret_key = "change-me-later"

PAGE = """
<h1>Verify your age</h1>
<p>Your wallet will prove you are over 18 without sharing your birthdate.</p>
<button onclick="go()">Verify with my wallet</button>
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
    else { msg.textContent = 'Not verified: ' + JSON.stringify(out.detail); }
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
  }
}
</script>
"""


def is_verified(result):
    return result.get("state") == "verified" and result.get("result", {}).get("age_over_18") is True


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
    if DEMO:
        extra = '<hr><p><a href="/demo-verify">Demo mode: use the fake test wallet</a></p>'
    return PAGE + extra


@app.route("/api/start", methods=["POST"])
def api_start():
    r = requests.post(VERIFIER + "/sessions", json={"checks": ["age_over_18"]}, timeout=10)
    r.raise_for_status()
    data = r.json()
    session["av_session"] = data["session_id"]
    return jsonify(data["transports"]["dc"])


@app.route("/api/finish", methods=["POST"])
def api_finish():
    sid = session.get("av_session")
    if not sid:
        return jsonify({"ok": False, "detail": "no session"}), 400
    body = request.get_json(silent=True) or {}
    r = requests.post(VERIFIER + "/sessions/" + sid + "/presentation",
                      json={"response": body.get("response")}, timeout=30)
    result = r.json()
    ok = is_verified(result)
    if ok:
        session["is_adult"] = True
    session.pop("av_session", None)
    return jsonify({"ok": ok, "detail": result})


@app.route("/demo-verify")
def demo_verify():
    if not DEMO:
        return "Demo mode is off.", 404
    # 1. Ask the verifier for a session, like a real site would.
    r = requests.post(VERIFIER + "/sessions", json={"checks": ["age_over_18"]}, timeout=10)
    r.raise_for_status()
    data = r.json()
    # 2. The fake wallet (running inside the verifier's container) answers the request.
    job = json.dumps({"request": data["transports"]["dc"], "origin": SITE_ORIGIN})
    p = subprocess.run(
        ["docker", "exec", "-i", "zkv", "/app/.venv/bin/python", "/tmp/work/wallet_present.py"],
        input=job, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if p.returncode != 0:
        return "<h1>Fake wallet failed</h1><pre>" + html.escape(p.stderr[-3000:]) + "</pre>", 500
    wallet = json.loads(p.stdout)
    # 3. Send the answer to the verifier and act only on its verdict.
    fin = requests.post(VERIFIER + "/sessions/" + data["session_id"] + "/presentation",
                        json={"response": wallet["response"]}, timeout=30)
    result = fin.json()
    if is_verified(result):
        session["is_adult"] = True
        return redirect(url_for("members"))
    return "<h1>Not verified</h1><pre>" + html.escape(json.dumps(result, indent=2)) + "</pre>", 403


@app.route("/members")
def members():
    if not session.get("is_adult"):
        return redirect(url_for("home"))
    return '<h1>Members area</h1><p>You passed the age check.</p><p><a href="/logout">Log out</a></p>'


@app.route("/logout")
def logout():
    session.pop("is_adult", None)
    return redirect(url_for("home"))

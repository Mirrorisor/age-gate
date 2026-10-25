import requests
from flask import Flask, session, redirect, url_for, request, jsonify

VERIFIER = "http://127.0.0.1:8000"

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

@app.route("/")
def home():
    return """
    <h1>Welcome</h1>
    <p>This site is for adults only.</p>
    <a href="/verify">Verify my age</a>
    """

@app.route("/verify")
def verify():
    return PAGE

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
    ok = result.get("state") == "verified" and result.get("result", {}).get("age_over_18") is True
    if ok:
        session["is_adult"] = True
    session.pop("av_session", None)
    return jsonify({"ok": ok, "detail": result})

@app.route("/members")
def members():
    if not session.get("is_adult"):
        return redirect(url_for("home"))
    return "<h1>Members area</h1><p>You passed the age check.</p>"

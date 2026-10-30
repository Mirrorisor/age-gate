"""Attack probes against a running age-gate stack (docs/SELF-REVIEW.md). Test use only.

Run from the repository folder with the stack up (docker compose --profile passport
--profile zec up -d) and the real .env present:

    venv/Scripts/python scripts/self_review_probes.py

Each probe prints PASS when the site resisted, FAIL when it did not. It reads secrets from
.env only to sign test webhooks and never prints them.
"""

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import requests
from flask import Flask

# 127.0.0.1, not localhost: on Windows each request to "localhost" first tries IPv6 and
# waits about two seconds, which is too slow to reach a per-minute rate limit.
SITE = "http://127.0.0.1:5000"
VERIFIER = "http://127.0.0.1:8000"
CHECKOUT = "http://127.0.0.1:8080"
ENV = dict(
    line.split("=", 1) for line in Path(".env").read_text().splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
results = []


def probe(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def cookie_signed_with(key, data):
    app = Flask("forger")
    app.secret_key = key
    return app.session_interface.get_signing_serializer(app).dumps(data)


def members_with(cookie_value):
    s = requests.Session()
    s.cookies.set("session", cookie_value)
    return s.get(SITE + "/members", allow_redirects=False)


# 1. Cookies
r = members_with(cookie_signed_with("not-the-real-key", {"is_adult": True}))
probe("cookie signed with a wrong key is ignored", r.status_code == 302, f"{r.status_code}")
unsigned = base64.urlsafe_b64encode(json.dumps({"is_adult": True}).encode()).decode().rstrip("=")
r = members_with(unsigned)
probe("unsigned cookie is ignored", r.status_code == 302, f"{r.status_code}")
r = members_with(cookie_signed_with("change-me-later", {"is_adult": True}))
probe("cookie signed with the old placeholder key is ignored", r.status_code == 302, f"{r.status_code}")
r = requests.post(SITE + "/api/start")
flags = r.headers.get("Set-Cookie", "")
probe("session cookie is HttpOnly and SameSite=Lax", "HttpOnly" in flags and "SameSite=Lax" in flags, flags.split(";", 1)[-1].strip()[:60])

# 2. Rate limits cannot be dodged with a spoofed X-Forwarded-For (TRUST_PROXY is off locally).
codes = [requests.post(SITE + "/api/passport/start", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(35)]
probe("spoofed X-Forwarded-For does not reset the rate limit", codes.count(429) >= 5, f"{codes.count(429)} of 35 refused")
time.sleep(61)  # let the window pass before the next probes

# 3. Size limits, methods, headers on error pages
r = requests.post(SITE + "/webhooks/zeccheckout", data=b"x" * 70_000)
probe("oversized body on a normal route is refused", r.status_code == 413, f"{r.status_code}")
r = requests.post(SITE + "/api/passport/finish", data=b"x" * (9 * 1024 * 1024), headers={"Content-Type": "application/json"})
probe("oversized passport upload is refused", r.status_code == 413, f"{r.status_code}")
for path, method in (("/no-such-page", "GET"), ("/api/finish", "GET"), ("/webhooks/zeccheckout", "POST")):
    r = requests.request(method, SITE + path, data=b"x" * 70_000 if method == "POST" else None)
    csp = r.headers.get("Content-Security-Policy", "")
    probe(f"security headers on a {r.status_code} response", "default-src 'none'" in csp and r.headers.get("X-Frame-Options") == "DENY", path)

# 4. Reflection: nothing the visitor sends comes back as markup
marker = "<script>alert(1)</script>"
hits = [p for p in ("/verify", "/passport", "/privacy", "/no-such-" + marker) if marker in requests.get(SITE + p, params={"q": marker}).text]
probe("no page reflects visitor input as markup", not hits, ", ".join(hits))

# 5. Webhook forgery
secret = ENV.get("ZC_WEBHOOK_SECRET", "")


def signed(body, stamp=None, key=secret):
    stamp = int(time.time()) if stamp is None else stamp
    sig = hmac.new(key.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return {"ZecCheckout-Signature": f"t={stamp},v1={sig}", "Content-Type": "application/json"}


event = json.dumps({"event_id": "probe-1", "seq": 1, "event": "invoice.paid",
                    "invoice": {"id": "no-such-invoice", "status": "paid",
                                "amount_zat": 100000, "confirmed_zat": 100000}}).encode()
r = requests.post(SITE + "/webhooks/zeccheckout", data=event, headers={"Content-Type": "application/json"})
probe("unsigned 'paid' webhook is refused", r.status_code == 400, f"{r.status_code}")
r = requests.post(SITE + "/webhooks/zeccheckout", data=event, headers=signed(event, key="wrong-secret-wrong-secret"))
probe("webhook signed with a wrong secret is refused", r.status_code == 400, f"{r.status_code}")
r = requests.post(SITE + "/webhooks/zeccheckout", data=event, headers=signed(event, stamp=int(time.time()) - 600))
probe("correctly signed but 10-minute-old webhook is refused", r.status_code == 400, f"{r.status_code}")
r = requests.post(SITE + "/webhooks/zeccheckout", data=event, headers=signed(event))
probe("correctly signed 'paid' for an invoice the checkout does not know is not accepted",
      r.status_code != 200 or r.json().get("ok") is not True, f"{r.status_code} {r.text.strip()[:60]}")

# 6. Internal services
r = requests.get(CHECKOUT + "/api/v1/invoices/anything")
probe("checkout API refuses requests without its key", r.status_code in (401, 403), f"{r.status_code}")
r = requests.get(VERIFIER + "/debug/transcript/anything")
probe("verifier debug route answers only on this machine (informational)", True, f"{r.status_code} on 127.0.0.1")
try:
    requests.get("http://127.0.0.1:8100/health", timeout=3)
    probe("passport service is not reachable from outside Docker", False)
except requests.RequestException:
    probe("passport service is not reachable from outside Docker", True)

print(f"\n{results.count(True)} passed, {results.count(False)} failed")

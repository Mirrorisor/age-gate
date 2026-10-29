import os
import subprocess
import sys
from pathlib import Path

import app as site

ROOT = Path(__file__).resolve().parent.parent


def test_pages_carry_security_headers_and_a_matching_nonce():
    response = site.app.test_client().get("/verify")
    csp = response.headers["Content-Security-Policy"]
    page = response.get_data(as_text=True)
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" in csp
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert '<script nonce="' + nonce + '">' in page
    assert "<script>" not in page
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_the_verify_page_has_no_inline_event_handlers():
    page = site.app.test_client().get("/verify").get_data(as_text=True)
    assert "onclick" not in page
    assert "addEventListener('click', go)" in page


def test_each_response_gets_a_new_nonce():
    client = site.app.test_client()
    first = client.get("/verify").headers["Content-Security-Policy"]
    second = client.get("/verify").headers["Content-Security-Policy"]
    assert first != second


def test_private_pages_are_not_cached():
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["is_adult"] = True
    assert client.get("/members").headers["Cache-Control"] == "no-store"
    assert client.get("/pay/status").headers["Cache-Control"] == "no-store"
    assert "Cache-Control" not in client.get("/").headers


def test_api_start_is_rate_limited(monkeypatch):
    monkeypatch.setattr(site, "limiter", site.RateLimiter(3))
    monkeypatch.setattr(
        site.verifier, "start_session", lambda: {"session_id": "s", "offer": {"x": 1}}
    )
    client = site.app.test_client()
    codes = [client.post("/api/start").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = client.post("/api/start")
    assert blocked.headers["Retry-After"] == "60"
    assert "Too many" in blocked.get_json()["message"]


def test_rate_limit_is_per_address_and_forgets_after_the_window(monkeypatch):
    limiter = site.RateLimiter(1, window=0.0)
    assert limiter.allow("a")
    assert limiter.allow("a")  # window of 0 seconds: the first hit has already aged out
    strict = site.RateLimiter(1)
    assert strict.allow("a")
    assert not strict.allow("a")
    assert strict.allow("b")


def test_rate_limit_of_zero_means_off():
    limiter = site.RateLimiter(0)
    assert all(limiter.allow("a") for _ in range(100))


def test_other_pages_are_not_rate_limited(monkeypatch):
    monkeypatch.setattr(site, "limiter", site.RateLimiter(1))
    client = site.app.test_client()
    assert [client.get("/privacy").status_code for _ in range(5)] == [200] * 5


def test_oversized_webhook_body_is_refused():
    response = site.app.test_client().post("/webhooks/zeccheckout", data=b"x" * 70_000)
    assert response.status_code == 413


def test_a_real_sized_proof_upload_is_accepted_but_a_huge_one_is_not():
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["av_session"] = "abc"
    proof = {"response": "x" * 600_000}  # a real wallet proof is several hundred kilobytes
    assert client.post("/api/finish", json=proof).status_code != 413
    huge = {"response": "x" * (site.PROOF_UPLOAD_LIMIT + 1)}
    refused = client.post("/api/finish", json=huge)
    assert refused.status_code == 413
    assert refused.get_json()["error"] == "too large"  # JSON, so the page can read it


def test_session_cookie_is_httponly_and_samesite_lax(monkeypatch):
    monkeypatch.setattr(
        site.verifier, "start_session", lambda: {"session_id": "s", "offer": {"x": 1}}
    )
    cookie = site.app.test_client().post("/api/start").headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def run_site(code, extra_env):
    env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "PAYMENT_GATE")}
    env.update(extra_env)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )


def test_without_a_secret_key_the_site_makes_a_random_one_each_run():
    code = "import app; print(app.app.secret_key)"
    first = run_site(code, {}).stdout.strip()
    second = run_site(code, {}).stdout.strip()
    assert len(first) == 64 and first != second
    assert first != "change-me-later"


def test_a_configured_secret_key_is_used_and_the_placeholder_is_not():
    code = "import app; print(app.app.secret_key)"
    assert run_site(code, {"SECRET_KEY": "r" * 40}).stdout.strip() == "r" * 40
    placeholder = run_site(code, {"SECRET_KEY": "change-me-later"}).stdout.strip()
    assert placeholder != "change-me-later"


def test_behind_a_trusted_proxy_the_visitor_address_comes_from_the_header():
    from flask import Flask, request

    demo = Flask(__name__)

    @demo.route("/who")
    def who():
        return request.remote_addr

    client = demo.test_client()
    headers = {"X-Forwarded-For": "203.0.113.7"}
    assert client.get("/who", headers=headers).get_data(as_text=True) == "127.0.0.1"
    site.trust_one_proxy(demo)
    assert client.get("/who", headers=headers).get_data(as_text=True) == "203.0.113.7"

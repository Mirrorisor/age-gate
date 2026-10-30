# Site hardening

What the website does to protect itself, and what it still does not do. This is a demo
on test certificates; none of this makes it fit for real users.

## What it does

- **Session cookie.** `HttpOnly` (scripts cannot read it) and `SameSite=Lax`. Set
  `SESSION_COOKIE_SECURE=1` once the site is served over https.
- **Secret key.** The cookie is signed with `SECRET_KEY`; anyone who knows the key can forge
  a "passed the age check" cookie. With no key set, the site makes a random one for each run
  (everyone is logged out on restart). The payment step still insists on a real key.
- **Rate limits.** `/api/start`, `/api/finish`, `/api/passport/start`, `/api/passport/finish`, `/pay` and `/demo-verify` allow
  `RATE_LIMIT_PER_MIN` requests per minute per address (default 30, `0` turns it off).
  Under Compose the counts live in a SQLite file (`RATE_LIMIT_DB`), so they survive a restart
  and every worker shares them; the file holds an HMAC of each address under `SECRET_KEY`,
  never the address, and deleted rows are overwritten. Behind a reverse proxy
  every visitor may share the proxy's address.
- **Browser protections.** A strict Content-Security-Policy (only this site's own scripts,
  which carry a fresh nonce on each response, and no framing), plus `nosniff`,
  `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. Private pages are sent with
  `Cache-Control: no-store`.
- **Request size.** Bodies over 64 KB are refused, except the wallet's proof upload
  (`/api/finish`), which may be up to 4 MB, and the passport proofs (`/api/passport/finish`),
  up to 8 MB. Refusals are answered in JSON.
- **Server.** The container runs gunicorn rather than Flask's development server.

## What it does not do

- No accounts, no logging of who you are, and no protection against someone who already holds
  a valid cookie.
- Rate limits are per address, not per person. They slow down abuse; they do not stop a
  determined one.
- Run it behind https before anyone real uses it. `docker-compose.https.yml` does that with Caddy
  for a real domain: see [HTTPS.md](HTTPS.md).
- The verifier it relies on is experimental; see the README's known problems.

## How the privacy claims are kept honest

`tests/test_privacy_audit.py` runs with the other tests and fails if the site starts storing
or showing more than `/privacy` says: the session cookie may only hold `av_session`,
`is_adult`, `invoice_id` and, during a passport check, `passport_scope` and `passport_scope_at`
(a random code and when it was made); it must never contain the proof or any claim; the proof is not
echoed back; no page loads anything from another site; every page sends
`Referrer-Policy: no-referrer`; and visiting a page sets no cookie. If a test fails, either
the site changed what it collects or the privacy page must change. Do not edit the test to
make it pass.

# Site hardening

What the website does to protect itself, and what it still does not do. This is a demo
on test certificates; none of this makes it fit for real users.

## What it does

- **Session cookie.** `HttpOnly` (scripts cannot read it) and `SameSite=Lax`. Set
  `SESSION_COOKIE_SECURE=1` once the site is served over https.
- **Secret key.** The cookie is signed with `SECRET_KEY`; anyone who knows the key can forge
  a "passed the age check" cookie. With no key set, the site makes a random one for each run
  (everyone is logged out on restart). The payment step still insists on a real key.
- **Rate limits.** `/api/start`, `/api/finish`, `/pay` and `/demo-verify` allow
  `RATE_LIMIT_PER_MIN` requests per minute per address (default 30, `0` turns it off).
  Counts live in memory, so the container runs one worker process. Behind a reverse proxy
  every visitor may share the proxy's address.
- **Browser protections.** A strict Content-Security-Policy (only this site's own scripts,
  which carry a fresh nonce on each response, and no framing), plus `nosniff`,
  `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. Private pages are sent with
  `Cache-Control: no-store`.
- **Request size.** Bodies over 64 KB are refused, except the wallet's proof upload
  (`/api/finish`), which may be up to 4 MB. Refusals are answered in JSON.
- **Server.** The container runs gunicorn rather than Flask's development server.

## What it does not do

- No accounts, no logging of who you are, and no protection against someone who already holds
  a valid cookie.
- Rate limits are per address, not per person. They slow down abuse; they do not stop a
  determined one.
- Run it behind https (a reverse proxy such as Caddy or traefik) before anyone real uses it.
- The verifier it relies on is experimental; see the README's known problems.

# Changelog

## Unreleased

- Optional passport route: `/passport` lets a visitor prove 18+ with the ZKPassport app (QR code or link). The new `passport/` service checks the proofs locally (never through ZKPassport's API), rebuilds the query itself and drops ZKPassport's per-site identifier. Off unless `PASSPORT_URL` is set; dev mode (mock passports only) by default. Only the passport page may open WebSocket connections (to ZKPassport's relay).
- `docker-compose.https.yml`, `Caddyfile` and `docs/HTTPS.md`: HTTPS on a real domain with Caddy (automatic certificates, HSTS, secure cookies, no access log, the site reachable only through the proxy).
- CI runs the passport end-to-end check (`.github/workflows/e2e.yml`) on every push to main and weekly, against the site and the reusable `PassportGate`.
- Payments checked against our own node (roadmap M2): Tested 2026-10-30: with `ZC_LIGHTWALLETD` pointing at our node, a 0.001 TAZ shielded payment from Zingo was detected and marked paid, and the site recorded it, with no public chain server in the path.
- `docs/SELF-REVIEW.md`: an internal self-review, 38 attacks against the running stack. Fixes: the CSP nonce goes only into the site's own scripts; the gates refuse control characters and backslashes in redirect targets; the passport service refuses proof sets with repeated or missing pieces.
- `docs/CREDENTIAL-SIZE.md` and `scripts/measure_mso_limit.py`: why larger credentials fail (a 2,533-byte MSO, about 62 fields), and a C++ prover crash on nested fields. Corrects the README, which blamed portraits.
- `docs/VERIFIER-MAINTENANCE.md`: the routine for keeping the verifier fork safe, and its first run. CI now audits the site's and the passport service's packages weekly.
- `agecheck.flask_passport.PassportGate`: the passport check as a drop-in Flask blueprint, sharing its pass with `AgeGate`; `examples/passport_site.py` offers both. The scope record and service client moved to `agecheck.passport`, which the site now uses too.
- The stack now runs our verifier fork by default (upstream has not responded to its fixes); `docker-compose.upstream.yml` runs upstream's image for comparison and replaces `docker-compose.fork.yml`.
- Rate limits are kept in a SQLite file under Compose (`RATE_LIMIT_DB`), shared by every worker and kept across restarts. It holds an HMAC of each address under `SECRET_KEY`, never the address, and overwrites deleted rows.
- Used passport scopes are kept in a SQLite file under Compose (`PASSPORT_SCOPES_DB`), so a restart cannot give a used check a second try.
- `docs/THREAT-MODEL.md` and `docs/ROADMAP.md`: the whole system's threats and gaps, and funded milestones.
- A passport visit's scope is now recorded on the server when tried, so resending an old session cookie cannot reuse it, and it expires after 15 minutes. Found by the new `scripts/e2e.ps1`, which checks the passport route end to end with mock passports.
- Every dependency is pinned to what was tested (image digests, `requirements-site.txt`, `passport/bun.lock`, the ZKPassport commit the test phone uses); CI also builds the passport service and the site image.
- Passport proofs are tied to the visit that asked for them: every `/passport` visit gets its own random scope, usable once, so a captured proof cannot be replayed in another session.
- `scripts/go-public.ps1` puts the stack on a temporary public https address (Cloudflare quick tunnel) for testing, and `-Stop` puts it back. New `TRUST_PROXY=1` setting reads the visitor address from the proxy header for rate limiting. Compose now passes `SITE_ORIGIN`, `SESSION_COOKIE_SECURE`, `TRUST_PROXY`, `RATE_LIMIT_PER_MIN` and `INVOICE_RETENTION_DAYS` through from `.env`.
- Invoices untouched for 30 days are deleted (`INVOICE_RETENTION_DAYS`, 0 keeps them). Older invoice files are upgraded in place.
- The payment page asks visitors to pay from a shielded balance, and the privacy page says the verifier sees which organisation issued the credential.
- Logging out now clears the whole session cookie, including the invoice number. Before, a paid invoice stayed in the cookie, so the next person on a shared browser who passed the age check got in without paying, and their visit was tied to the previous person's.

## 0.1.0

- First release of the age-check client (`AgeVerifier`, `is_verified`, `VerifierError`).
- Flask demo site with a members page gated by a zero-knowledge over-18 check.
- Works end to end with a real Android wallet (Multipaz Test App, Age Verification document) and with a fake wallet in demo mode.
- Known limits: only the `eu.europa.ec.av.1` document type is accepted; the verifier is experimental; demo certificates are for local testing only.
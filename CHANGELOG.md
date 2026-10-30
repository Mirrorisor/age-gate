# Changelog

## Unreleased

- Optional passport route: `/passport` lets a visitor prove 18+ with the ZKPassport app (QR code or link). The new `passport/` service checks the proofs locally (never through ZKPassport's API), rebuilds the query itself and drops ZKPassport's per-site identifier. Off unless `PASSPORT_URL` is set; dev mode (mock passports only) by default. Only the passport page may open WebSocket connections (to ZKPassport's relay).
- `scripts/go-public.ps1` puts the stack on a temporary public https address (Cloudflare quick tunnel) for testing, and `-Stop` puts it back. New `TRUST_PROXY=1` setting reads the visitor address from the proxy header for rate limiting. Compose now passes `SITE_ORIGIN`, `SESSION_COOKIE_SECURE`, `TRUST_PROXY`, `RATE_LIMIT_PER_MIN` and `INVOICE_RETENTION_DAYS` through from `.env`.
- Invoices untouched for 30 days are deleted (`INVOICE_RETENTION_DAYS`, 0 keeps them). Older invoice files are upgraded in place.
- The payment page asks visitors to pay from a shielded balance, and the privacy page says the verifier sees which organisation issued the credential.
- Logging out now clears the whole session cookie, including the invoice number. Before, a paid invoice stayed in the cookie, so the next person on a shared browser who passed the age check got in without paying, and their visit was tied to the previous person's.

## 0.1.0

- First release of the age-check client (`AgeVerifier`, `is_verified`, `VerifierError`).
- Flask demo site with a members page gated by a zero-knowledge over-18 check.
- Works end to end with a real Android wallet (Multipaz Test App, Age Verification document) and with a fake wallet in demo mode.
- Known limits: only the `eu.europa.ec.av.1` document type is accepted; the verifier is experimental; demo certificates are for local testing only.
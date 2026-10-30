# Threat model

The whole system as it runs in this repository, October 2026. It is a test-only demo
(test certificates, mock passports, Zcash testnet); this page is here so a reviewer can
check the reasoning, not to claim it is safe for real users. Details of the site's own
defences are in [HARDENING.md](HARDENING.md), and of the passport route in
[REVIEW-PASSPORT.md](REVIEW-PASSPORT.md).

## What it protects

1. **The gate.** `/members` opens only for a session that passed an over-18 check and, when
   `PAYMENT_GATE=1`, paid its own invoice.
2. **The visitor's privacy.** The site learns "over 18: yes" and, with payments, "this invoice
   was paid". It keeps no birthdate, name, ID number, nationality or proof, and nothing that
   links two visits. `tests/test_privacy_audit.py` checks this against `/privacy`.
3. **The operator's secrets.** `SECRET_KEY`, the ZecCheckout API key and webhook secret, and
   the viewing key (`ZC_UFVK`). The viewing key can see payments but never spend.

## The parts, and how far each is trusted

| Part | Where it runs | Trusted for |
|---|---|---|
| Visitor's browser and wallet/phone | Visitor | Nothing. Anything it sends is checked. |
| Site (`app.py`, Flask + gunicorn) | This machine, port 5000 on 127.0.0.1 | Everything below; it makes the final decision. |
| Verifier (`zk-age-verifier`, our fork) | Container, 127.0.0.1:8000 | Checking mdoc ZK proofs and the issuer chain against the roots in `verifier-config/certs`. |
| Passport service (`passport/`) | Container, no published port | Checking ZKPassport proofs locally against ZKPassport's on-chain registries. |
| ZecCheckout | Container, 127.0.0.1:8080 | Telling the site an invoice was paid. Holds only a viewing key. |
| Public lightwalletd (`testnet.zec.rocks`) | Third party | Chain data for ZecCheckout. **Not verified**: ZecCheckout does not check proof-of-work. |
| Zebra testnet node | This machine | Not used by the stack yet. |
| ZKPassport relay | Third party | Carrying messages between the phone and the browser. The proofs it carries are checked by the passport service, not trusted. |
| Ethereum RPC (Sepolia in dev mode) | Third party | Registry roots the passport service checks proofs against. |
| Cloudflare quick tunnel (optional) | Third party | Only when `go-public.ps1` is running; sees visitors' addresses and the pages they open. |

## Threats and what answers them

| # | Threat | Answer | Checked by |
|---|---|---|---|
| T1 | Visitor claims "over 18" without a valid proof | The site never trusts the browser's verdict; it asks the verifier or the passport service and acts only on their answer. | `tests/test_site.py`, `tests/test_passport.py`, `scripts/e2e.ps1` (minor) |
| T2 | Visitor swaps the question (asks a weaker query) | Both checkers rebuild the query themselves: `age_over_18` for mdoc, `age >= 18` with nothing disclosed for passports; extra result keys are refused. | `passport/check.ts`; verifier's own tests |
| T3 | Replaying a captured valid proof | mdoc: the proof is bound to one verifier session's transcript (the origin and that session's encryption info), and sessions expire after 300 seconds; this is the verifier's design, not tested here. Passport: a random scope per check, recorded on the server when tried, expiring after 15 minutes. | Passport: `tests/test_passport.py`, `scripts/e2e.ps1` (two replays) |
| T4 | Proof made for another site | The domain comes from `SITE_ORIGIN`, never from the visitor; a proof for another domain is refused. | Manual test 2026-10-30 (localhost vs tunnel) |
| T5 | Forged "passed" cookie | Cookie signed with `SECRET_KEY`; a random key if none is set; the payment step refuses to start without a real one. | `tests/test_site_hardening.py` |
| T6 | Fake "paid" webhook | HMAC signature with a 5-minute window, duplicate events ignored, and the site asks ZecCheckout for the invoice again and checks the amount before marking it paid. | `tests/test_payment.py`, `tests/test_hardening.py` |
| T7 | Using someone else's paid invoice | The invoice number lives in the visitor's own session; logout clears the whole session. | `tests/test_privacy_audit.py` |
| T8 | Hostile lightwalletd makes an unpaid invoice look paid | **Not answered.** ZecCheckout trusts the public server. | Known gap |
| T9 | Untrusted issuer accepted | The verifier trusts only the roots in its `certs` folder. Which roots go there is the operator's call. | Verifier tests; the fork's `--check-cert` option explains a refusal |
| T10 | Mock passports accepted in production | `PASSPORT_DEV_MODE=1` is the default and accepts only mock passports; turning it off is a deliberate step the docs say not to take yet. | `passport/server.ts` |
| T11 | Script injection, framing, leaks to other sites | Strict CSP with a nonce, no framing, `no-referrer`, no third-party loads (the passport page may also open `wss:` to the relay). | `tests/test_site_hardening.py`, `tests/test_privacy_audit.py` |
| T12 | Flooding or huge uploads | Per-address rate limits; 64 KB body limit except proof uploads (4 MB mdoc, 8 MB passport). | `tests/test_site_hardening.py` |
| T13 | Tracking a visitor across visits | No accounts; the passport route drops ZKPassport's per-site identifier; visiting a page sets no cookie. | `tests/test_privacy_audit.py` |
| T14 | A dependency changes under us | Images pinned by digest, Python packages and `bun.lock` pinned, CI builds both images. | CI (`tests.yml`) |
| T15 | Exposed internal services | Verifier, checkout and site bind to 127.0.0.1; the passport service publishes no port. This matters: the verifier has no login and an unauthenticated development route, `/debug/transcript`. | `docker-compose.yml` |

## Known gaps, stated plainly

- **T8:** payments rest on a public lightwalletd that ZecCheckout does not verify. The fix is
  to point ZecCheckout at a node we run.
- **In-memory state:** rate limits and the used-scope record live in one process; a restart
  forgets them (used scopes for up to 15 minutes).
- **Single machine:** one worker, SQLite for invoices. Fine for a demo, not for traffic.
- **Shared cookies:** anyone holding a visitor's "passed" cookie gets in. Nothing session-based
  can stop a visitor handing their cookie to someone else.
- **No external review yet** of the site, the passport service, the verifier (pre-alpha by its
  own description) or ZecCheckout (a prototype). ZKPassport states it has not been audited.
- **Real credentials untested:** real passports, and government-issued mdocs.

## Out of scope

The phone's operating system and wallet app, the browser itself, the operator's own machine,
and the cryptography of Longfellow ZK and ZKPassport's circuits, which are trusted as published.

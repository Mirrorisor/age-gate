# Review request: the passport age check

A short brief for someone kind enough to review the optional passport route before it is
ever used with real passports. It is small: about 190 lines of TypeScript plus a few
routes in `app.py`.

## What it claims

1. The site opens `/members` only after a ZKPassport proof that the holder is 18 or over.
2. The site learns nothing else: no name, birthdate, nationality, passport number, and no
   identifier that links two visits.
3. A proof only works in the visit that asked for it.

## What to read

| File | What it does |
|---|---|
| `passport/check.ts` | Rebuilds the query (age >= 18, nothing disclosed), rejects any other result keys, checks the scope prefix, calls the SDK's `verify()` with `verifierMode: "local"`. Fails closed. |
| `passport/server.ts` | Internal HTTP service (`POST /verify`), not published on any port; only the site calls it. Keeps nothing. |
| `passport/client.ts` | Browser side: opens the request with the visit's scope, shows the QR, posts proofs to the site. Untrusted by design. |
| `app.py`: `passport_page`, `passport_finish`, `passport_check` | Makes a random scope per visit (`age-over-18:` + 16 random bytes, base64url), stores it in the signed session, uses it once, passes the site's own domain (from `SITE_ORIGIN`, never from the visitor). |

## Threat model, as I understand it

- The visitor's browser is untrusted: it can send any proofs and any result.
- The passport service is trusted and reachable only from the site.
- The session cookie is signed with `SECRET_KEY`; forging it is out of scope here.
- ZKPassport's SDK, circuits and on-chain registries are trusted as they are.

## Specific questions

1. Is the per-visit scope a sound way to stop replay? Asked upstream too:
   <https://github.com/zkpassport/zkpassport-packages/issues/385>.
2. Does a proof have its own validity window, and should the site also check a date?
3. Is dropping the unique identifier enough for unlinkability, or does anything else in
   `proofs` or `result` identify the holder or the passport?
4. Anything that would make `check.ts` return true for something other than "18 or over",
   for example a different query, domain, or a dev-mode proof when dev mode is off.
5. Errors: every verifier failure (including an RPC outage) returns false. Is that the right
   call, and is anything logged that should not be?

## How to run it

- Tests: `venv/Scripts/python -m pytest` (139 tests; `tests/test_passport.py` covers the routes).
- Live, with a mock passport: see [passport/README.md](../passport/README.md) and
  [scripts/test-phone](../scripts/test-phone/README.md). Dev mode only.

## Known limits

- Tested only in dev mode with mock passports.
- Neither ZKPassport (by its own statement) nor this service has had an external audit.

# Passport service (optional, test only)

Lets a visitor prove they are 18 or over with a passport or ID card through the
[ZKPassport](https://github.com/zkpassport/zkpassport-packages) app (Apache-2.0).

- The proofs are checked here, on this server (`verifierMode: "local"`); they are never sent
  to ZKPassport's verifier API.
- The query is rebuilt here (age >= 18, nothing disclosed), so a visitor cannot swap the question.
- The per-site identifier ZKPassport proofs carry is dropped, so visits cannot be linked.
- `PASSPORT_DEV_MODE=1` (the default) accepts only mock passports from the fictional
  "Zero Knowledge Republic" and reads ZKPassport's Sepolia testnet registries. Keep it that way:
  no real passports until an outside security review.
- Checking reads ZKPassport's certificate and circuit registries on Ethereum, so the service needs
  internet access (`PASSPORT_RPC_URL` sets your own RPC).
- ZKPassport states it has not had an external audit yet.

## Tested (dev mode, mock passports, through a Cloudflare tunnel, 2026-10-30)

- Born 1995-11-12: proofs accepted, then payment, then the members area.
- Born 2015-01-01: the test phone cannot prove ("Age is not above or equal to min age"); nothing is
  sent and the visitor stays out.
- A proof made for another domain (`d=localhost` while the site expected the tunnel address) is
  refused with "The proof comes from a different domain than the one expected". Open the site at
  the same address as `SITE_ORIGIN` when testing.
- Each visit to `/passport` gets a new random scope (`age-over-18:<random>`), kept in the session
  for 15 minutes; proofs are made for it. The site records each scope when it is tried and refuses
  it after that, even if the visitor resends the session cookie from before (the session lives in
  the cookie, so removing the scope from it alone was not enough). A captured, valid proof is
  refused when sent again in the same visit (400) and in a later visit ("The proof uses a
  different scope than the one expected"). `scripts/e2e.ps1` checks all of this in one go. With
  Compose the record is a SQLite file (`PASSPORT_SCOPES_DB`), so a restart forgets nothing;
  without that setting it is kept in memory.
- Not tested: real passports, non-dev mode.

Start it with the site:

```
docker compose -f docker-compose.yml -f docker-compose.fork.yml --profile passport up -d --build
```

and set `PASSPORT_URL=http://passport:8100` in `.env`. The site then shows "Or use your passport".

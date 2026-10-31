# The verification service, for a site in any language

`agecheck.service` runs the age check for a site that is not written in Python, or that would
rather not handle proofs itself. The site runs it next to itself, as it would a database; there
is no central service. Test use only for now, like the rest of the toolkit (dev mode, mock
passports, test issuers).

## How it works

```
visitor's browser                site                         verification service
       |   GET /members           |                                     |
       |------------------------->|  not verified: make a nonce,        |
       |   302 to the service     |  remember it for this visitor       |
       |<-------------------------|                                     |
       |   GET /start?nonce=N  ------------------------------------------>|
       |   ... passport or phone-wallet check (QR, proofs) ... ----------->|
       |   302 to CALLBACK_URL?token=T  <----------------------------------|
       |   GET /age-callback?token=T|                                     |
       |------------------------->|  check T: signature, expiry,        |
       |   in                     |  this site, nonce N (then forget N) |
```

1. **The site** makes a one-time code (the nonce: 16 to 128 characters from `A-Z a-z 0-9 _ -`),
   stores it in the visitor's session, and redirects to `<service>/start?nonce=<nonce>`.
2. **The service** runs the check: the passport route, the phone-wallet route, or a choice of the
   two, depending on its settings.
3. **On a pass**, it redirects to the one configured `CALLBACK_URL` with `?token=<token>` and
   clears its own session. On a failure there is no token.
4. **The site** checks the token and lets the visitor in.

The service never redirects anywhere but `CALLBACK_URL`, never learns who the visitor is, and
keeps nothing after the handoff.

## The token

```
base64url(payload) "." base64url(HMAC-SHA256(SERVICE_SECRET, base64url(payload)))
```

without `=` padding, where the payload is JSON:

```json
{"v": 1, "over18": true, "nonce": "<the site's nonce>", "aud": "<the site's origin>", "exp": 1793404800}
```

The site must check, in order:

1. **The signature,** with a constant-time comparison, using the secret it shares with the service.
2. `v` is `1` and `over18` is `true`.
3. `exp` (Unix seconds) has not passed. Tokens live 120 seconds.
4. `aud` is the site's own origin (scheme, host and port, no path).
5. `nonce` is the one it stored for this visitor, and it **forgets that nonce on first use**, pass
   or fail, so a token cannot be used twice or by another visitor.

`examples/node-site/server.js` does all five in about twenty lines of Node, with no
dependencies. In Python, `agecheck.handoff.check()` does the same.

The token travels in a URL, so the callback page should send `Referrer-Policy: no-referrer`
(the Node example and the service both do). It is useless after 120 seconds and after one use.

## Running it

With Compose, alongside the passport service:

```
docker compose --profile service --profile passport up -d
```

Settings, in `.env`:

| Setting | Meaning |
|---|---|
| `SERVICE_CALLBACK_URL` | The site's callback, such as `https://example.com/age-callback` (required) |
| `SERVICE_SECRET` | The secret shared with the site, 32 characters or more (required) |
| `SERVICE_DOMAIN` | The service's host name as visitors see it; passport proofs are made for it |
| `SERVICE_PASSPORT_URL` | The passport service; default `http://passport:8100` |
| `SERVICE_VERIFIER_URL` | The zk-age-verifier service, to offer the phone-wallet route too; empty turns it off |
| `PASSPORT_DEV_MODE` | `1` (default): mock passports only |

It listens on `127.0.0.1:8200`. Put it behind https on its own host name (see
[HTTPS.md](HTTPS.md)), or behind the site's proxy on the same host; its cookie has its own name
(`agecheck_service`), so it does not collide with the site's.

## Adding another way to prove age

The two routes are both `Gate`s (`agecheck/flask_gate.py`): a Flask blueprint plus the shared
pass flag. A new credential type is a new `Gate` subclass that:

1. sets `verify_endpoint` to its verify page and builds `self.blueprint` with its routes;
2. checks the proof **on the server**, never trusting the browser's verdict;
3. calls `self._passed()` on success, which records the pass and returns where to go next.

`agecheck/flask_passport.py` (`PassportGate`, about 150 lines) is the worked example. Register
the new gate in `agecheck/service.py` next to the other two, and it becomes a choice on the
service's `/choose` page, with the same handoff and token.

## Tested

- `tests/test_service.py`: the token (valid; refused for a wrong secret, nonce, site, expiry,
  tampering or junk) and the service (pass, one handoff only, no token without a pass, malformed
  nonces, the callback as the only target, headers, its own cookie, rate limits).
- `scripts/test-phone/e2e-handoff.ts`, live with mock passports, and in CI: an adult goes from the
  Node site through the service and back in; the same token used twice, the token in another
  visitor's hands, and a tampered token are all refused; a minor gets no token.

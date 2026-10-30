# Running it over HTTPS on a real domain

`docker-compose.https.yml` puts [Caddy](https://caddyserver.com/) in front of the site. Caddy
gets a certificate from Let's Encrypt, renews it, redirects plain http to https, and passes
requests to the site. Everything else in the stack stays as it is.

This is still a test setup: test certificates, testnet, mock passports. Read
[THREAT-MODEL.md](THREAT-MODEL.md) before letting anyone real use it.

## What you need

- A domain or subdomain you control, such as `age.example.com`.
- A machine reachable from the internet, with ports **80 and 443** open to it. Caddy needs port
  80 to prove to Let's Encrypt that the domain is yours.
- A DNS `A` (and, if the machine has IPv6, `AAAA`) record pointing the domain at that machine.

## Steps

1. **In `.env`**, add the bare host name:

   ```
   SITE_DOMAIN=age.example.com
   ```

   The overlay sets the rest for the site: `SITE_ORIGIN=https://age.example.com`, secure cookies,
   and `TRUST_PROXY=1` (read the visitor's address from Caddy, the one proxy in front).

2. **Tell the verifier the new address.** In your `verifier-config/config.toml`, set

   ```
   expected_origin = "https://age.example.com"
   ```

   The phone wallet's proof includes the address it was made for, so it must match exactly. (The
   passport route needs no change: it takes the domain from `SITE_ORIGIN`.)

3. **Start everything with the overlay:**

   ```
   docker compose -f docker-compose.yml -f docker-compose.https.yml --profile passport up -d
   ```

   Add `--profile zec` for the payment step. Caddy fetches the certificate in the first minute;
   `docker compose logs caddy` shows it.

## Check it

- `https://age.example.com/verify` loads, and `http://age.example.com/verify` redirects to it.
- The response headers include `Strict-Transport-Security: max-age=31536000` and the site's own
  `Content-Security-Policy`.
- After pressing Start on `/passport`, the session cookie is marked `Secure; HttpOnly;
  SameSite=Lax`.
- Port 5000 is not reachable from outside: with the overlay the site has no published port, so
  nothing can go around Caddy.

All of these were checked on 2026-10-31 with `SITE_DOMAIN=localhost`, where Caddy uses its own
local certificate instead of Let's Encrypt. Also checked: 35 requests through Caddy, each with a
different forged `X-Forwarded-For`, were counted as one visitor (30 allowed, 5 refused), because
Caddy replaces the header with the real address; and Caddy's log contained no request paths.

## What it does not do

- **No access log, on purpose.** Caddy logs only its own events (certificates, errors). Add a
  `log` directive to the `Caddyfile` only if you are ready to say so on `/privacy`.
- **Who can see what.** Your hosting provider and anyone on the network path see that a
  visitor's address talked to your domain, as for any website. They do not see the pages or
  proofs, which travel inside https.
- **The other services stay private.** The verifier, ZecCheckout and lightwalletd are still
  published only on 127.0.0.1 and the passport service not at all. Do not open their ports.
- **Testing from your own laptop instead?** `scripts/go-public.ps1` gives a temporary public
  https address through a Cloudflare tunnel, with no domain or open ports needed.

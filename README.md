# age-gate: a zero-knowledge age check demo

A small learning project: a Flask website that gates a page behind a
zero-knowledge "over 18" check, using the experimental
[zk-age-verifier](https://pypi.org/project/zk-age-verifier/) service
(Longfellow ZK proofs over ISO mdoc, via the W3C Digital Credentials API).

The site never sees a birthdate or an ID. It only learns one thing: "this person
proved they are over 18."

> **Status: experimental demo.** The verifier itself says it is pre-alpha and
> should not be relied on. Do not use this to protect real users or content.

## What works, and what doesn't

Tested on Windows with Docker Desktop and Chrome, October 2026.

| Piece | Status |
|---|---|
| Flask site with a gated `/members` page | Works |
| Site asks the verifier for a session, Chrome shows the wallet QR prompt | Works |
| Verifier running in Docker, trusting a test issuer | Works |
| Fake wallet (test script) producing an encrypted ZK proof, verified by the running verifier | Works: returns `verified`, `age_over_18: True` |
| Real phone wallet producing a ZK proof | **Works** with the Multipaz Test App's **Age Verification** document, once the issuer's root certificate is in the verifier's `certs` folder (see "Using a real phone wallet"). Photo ID and mDL documents do not work (see known problems). |
| Real government-issued credentials | **Not tested.** Needs a supported wallet and the real issuer's root certificate. Support in Australia was not confirmed. |
| Flask site accepting a successful check end to end | **Works** with a real phone wallet and in demo mode (`DEMO_FAKE_WALLET=1`). The site opens `/members` only on a `verified` verdict. |
| A second wallet and issuer | **Works** with the EU Age Verification reference app and the EU demo issuer (see "Two wallets, two issuers (tested)"). |
| Optional payment step (`PAYMENT_GATE=1`) | **Works on the Zcash testnet only.** Tested with a fake checkout server and with the real ZecCheckout and a testnet wallet. Never use real funds. |
| Optional passport route (`/passport`, ZKPassport app) | **Works in dev mode with mock passports only**: a mock adult passed, paid on testnet and reached `/members`; a mock minor could not make a proof. Real passports **not tested**, on purpose (see "Prove age with a passport"). |

## How it fits together

```
Browser (Chrome)  <-->  Flask site (port 5000)  <-->  zk-age-verifier (Docker, port 8000)
      |                                                       ^
      +-- Digital Credentials API --> phone wallet            |
                                      (proof sent back through the site)
```

1. The site calls `POST /sessions` on the verifier and passes the wallet request to Chrome.
2. Chrome shows a QR code; the phone wallet builds a ZK proof.
3. The site forwards the wallet's response to `POST /sessions/{id}/presentation`.
4. The verifier replies `verified` with `age_over_18: true`, or a failure reason.

The verifier has no login of its own. Keep it reachable only from your own machine
(the Docker command below binds it to `127.0.0.1`).

## Run it

You need: Python 3.13 (3.15 failed to install the verifier's dependencies when
tested), Docker Desktop, and Chrome.

### 1. The website

```
py -3.13 -m venv venv
venv\Scripts\activate
pip install flask requests
flask run
```

Open <http://localhost:5000> (use `localhost`, not `127.0.0.1`; the verifier is
configured to expect exactly that origin).

### 2. The verifier

Create `verifier-config\config.toml`:

```toml
[service]
expected_origin = "http://localhost:5000"

[[trust.sources]]
pem = "/config/certs"
```

Put one or more issuer root certificates (PEM files) in `verifier-config\certs\`.
The verifier refuses to start with no trusted issuers. Only list issuers you
actually intend to trust.

```
docker run --rm --name zkv -p 127.0.0.1:8000:8000 -v %CD%\verifier-config:/config:ro -e ZK_AGE_VERIFIER_CONFIG=/config/config.toml ghcr.io/pipe23-org/zk-age-verifier:latest
```

(PowerShell: use `${PWD}` in place of `%CD%`.)

Check it: `Invoke-RestMethod http://127.0.0.1:8000/health` should return `status: ok`.

### 3. Test the proof system without a phone

`scripts/zkdemo.py` builds a fake credential with the Python library
`pylongfellow`, proves `age_over_18`, verifies it, and confirms that a false
claim is rejected. Run it inside the verifier's container, which already has the
library and the proof circuit:

```
docker run --rm -v %CD%\scripts:/demo --entrypoint /app/.venv/bin/python ghcr.io/pipe23-org/zk-age-verifier:latest /demo/zkdemo.py
```

`scripts/wallet_demo.py` goes further: it acts as a wallet against the *running*
verifier, including the response encryption. It relies on the verifier project's
own test code (`tests/integration/presenter.py` and the test credentials), which
is Apache-2.0 licensed and not copied into this repository. To use it:

1. Download <https://github.com/pipe23-org/zk-age-verifier> as a ZIP and extract it.
2. Copy `tests\integration\credentials\test-anchor.pem` into `verifier-config\certs\`
   (and remove any other certificates there), then restart the verifier.
3. Copy the extracted `tests` folder and the script into the running container, then run it:

```
docker exec zkv mkdir -p /tmp/work
docker cp <path-to-extracted-repo>\tests zkv:/tmp/work/tests
docker cp scripts\wallet_demo.py zkv:/tmp/work/wallet_demo.py
docker exec -e PYTHONDONTWRITEBYTECODE=1 zkv /app/.venv/bin/python /tmp/work/wallet_demo.py
```

Expected result: `verifier says: {'state': 'verified', 'result': {'age_over_18': True}, ...}`

### 4. Demo mode: the whole site, with the fake wallet

Demo mode lets you click through the real site flow without a phone. The site still
asks the verifier for a session and acts only on the verifier's verdict; the only
difference is that `scripts/wallet_present.py` (run inside the verifier's container
through `docker exec`) answers the wallet request instead of a phone.

Demo mode is **off by default** and must never be turned on for a public site, because
it signs people in with a test credential. It is enabled only by an environment variable.

With the verifier running (named `zkv`, as in step 2) and the test files copied in
(step 3):

```
docker cp scripts\wallet_present.py zkv:/tmp/work/wallet_present.py
venv\Scripts\activate
$env:DEMO_FAKE_WALLET = "1"
flask run
```

Open <http://localhost:5000/verify> and click **Demo mode: use the fake test wallet**.
You should land on the members page. Opening `/members` in a private window without
going through the check should send you back to the home page.

## Using a real phone wallet (Android, Multipaz Test App)

This is the path that worked end to end in testing. It uses Multipaz's **demo**
certificates, so it is for local testing only.

1. Install the Multipaz Test App on an Android phone.
2. Add an **Age Verification** document (document type `eu.europa.ec.av.1`).
   The verifier only accepts this type. Photo ID and mDL documents are rejected
   or fail on the phone.
3. Put the root certificate that signed your document into
   `verifier-config\certs\` and restart the verifier. For documents issued by the
   Test App's online issuer this was a certificate named `Multipaz TEST IACA`.
   Documents created offline inside the app use a private root that cannot be
   exported, so they cannot be trusted by this verifier.
4. Open <http://localhost:5000/verify> in Chrome, start the check, scan the QR
   code with the Test App, choose the Age Verification document and approve it.

### If you see `untrusted-issuer`

The verifier accepts a document-signer certificate only if it exactly matches a
trusted certificate, or was signed directly by one that is allowed to sign
certificates (`keyCertSign`). To see which certificate your wallet presented, copy
`core/trustlist.py` out of the container, add a few `print` lines to
`AnchorSet.resolve` that show the presented certificate's issuer and the loaded
anchors, and run the container with that file mounted over the original. The
issuer name tells you which root certificate to add. Nothing in this repository
depends on that change.

## Two wallets, two issuers (tested)

The same verifier accepted proofs from two unrelated wallet and issuer pairs, each
with its own test root certificate:

| Wallet | Credential came from | Root certificate the verifier needed |
|---|---|---|
| Multipaz Test App | Its online issuer (Age Verification document) | `Multipaz TEST IACA` |
| EU Age Verification reference app | The EU demo issuer's test kiosk | `Age Verification Issuer CA 01` (a test certificate published in the EU issuer's repository, under `api_docs/test_tokens/IACA-token/`) |

Both are demo roots. They belong in a local test setup only, never on a real site.

## Run it with Docker Compose

`docker compose up --build` starts the verifier and the site together.

1. Copy `.env.example` to `.env` and fill in `SECRET_KEY` (any long random string,
   for example from `python -c "import secrets; print(secrets.token_hex(32))"`) and
   `VERIFIER_CONFIG_DIR` (the folder holding `config.toml` and `certs\`).
2. Stop any verifier you started by hand (it uses port 8000).
3. `docker compose up --build`, then open <http://localhost:5000/verify>.

`.env` is ignored by git. Keep it that way. The site runs on Flask's built-in
server, which is fine for a local demo and not for the public internet.

### Trying the payment step with Compose

The Compose file can also start the fake checkout server from the payment section
below, so the whole payment flow runs with one command and no wallet or coins.

1. In `.env`, add these three lines (made-up values for local testing only):

   ```
   PAYMENT_GATE=1
   ZC_API_KEY=fake-api-key-for-local-testing-1234
   ZC_WEBHOOK_SECRET=fake-webhook-secret-for-local-testing-1234
   ```

2. `docker compose --profile fakepay up --build`
3. Pass the age check at <http://localhost:5000/verify>, open `/members` (it sends you
   to `/pay`), then open <http://127.0.0.1:8080/fake/> and click **Simulate payment**.

Payment records are kept in a Docker volume, so they survive `docker compose down`.
`docker compose down -v` deletes them. Without `--profile fakepay` the fake server does
not start, and with `PAYMENT_GATE` unset the site has no payment step at all.

## Checking your trusted certificates

```
python scripts\trustlist.py verifier-config\certs
```

lists every certificate the verifier will trust, with its name, dates, fingerprint
and whether it can sign other certificates. It warns about expired, soon-to-expire
and demo-looking certificates. It only reads files.

## Finding the root certificate a wallet needs

When a check ends with "This site does not trust the organisation that issued your
credential" (`untrusted-issuer`), the verifier gives no detail. To see which
certificate the wallet presented:

1. Copy `core/trustlist.py` out of the verifier container.
2. Add a few `print` lines at the start of `AnchorSet.resolve` that show the
   presented certificate's subject, issuer and fingerprint.
3. Start the container with that file mounted over the original, repeat the check,
   and read the issuer name in the verifier's output.
4. Find the issuer's published root certificate. Before trusting it, confirm that it
   really signed the presented certificate (name match and signature check).
   Then copy it into `certs\` and restart the verifier.

The presented certificate is public data. Never trust a root you have not checked
this way.

## Try the payment gate with a fake checkout server (no wallet, no coins)

The site can ask for a small shielded Zcash payment after the age check. It is **off by
default** and meant for the Zcash test network only. To try the whole flow without a
wallet, run a fake checkout server that "pays" invoices on request. It uses no
blockchain and no money.

1. Window 1, the fake checkout server:

```
venv\Scripts\activate
$env:ZC_API_KEY = "fake-api-key-for-local-testing-only"
$env:ZC_WEBHOOK_SECRET = "fake-webhook-secret-for-local-tests"
python scripts\fake_zeccheckout.py
```

2. Window 2, the site (with the verifier running as before):

```
venv\Scripts\activate
$env:PAYMENT_GATE = "1"
$env:SECRET_KEY = "any-long-random-text-for-local-testing"
$env:ZC_API_KEY = "fake-api-key-for-local-testing-only"
$env:ZC_WEBHOOK_SECRET = "fake-webhook-secret-for-local-tests"
$env:ZC_URL = "http://127.0.0.1:8080"
$env:SITE_ORIGIN = "http://localhost:5000"
flask --app app run
```

3. Pass the age check at <http://localhost:5000/verify>. The site then shows a payment
   page instead of the members page.
4. Open <http://127.0.0.1:8080/fake/> and press **Simulate payment**. The payment page
   switches to the members page within a few seconds.

How it is protected: the site accepts a payment message only if its HMAC signature is
valid and recent, ignores repeats and out-of-order messages, asks the checkout server to
confirm the invoice is really paid, and checks the amount. The site never holds a
spending key. Invoice state is kept in memory, so a restart forgets it; a real site would
need a database. A real ZecCheckout server needs a viewing key and a test-network wallet
to pay from, which this project has not set up yet.

## Real testnet payment with ZecCheckout

The payment step has also been run against the real
[ZecCheckout](https://github.com/samizdatproject/zeccheckout) server on the Zcash
**testnet**: pass the age check, get an invoice, pay 0.001 test ZEC (TAZ) from a testnet
wallet (Zingo desktop), and the members page opens once ZecCheckout reports the invoice
paid through a signed webhook. Testnet coins have no value. Never use real funds here.

ZecCheckout is a prototype and holds only a *viewing key*: it can see payments but cannot
spend. Read its own "Threat model" and "Limitations" before going further. In particular
it uses a public lightwalletd server and does not verify proof-of-work.

### Set it up

1. **Make a throwaway testnet viewing key.** ZecCheckout's `zc-keygen` prints a viewing
   key (UFVK) and saves the matching seed to a file. It can be built in Docker so you do
   not need Rust:

   ```
   git clone https://github.com/samizdatproject/zeccheckout.git zeccheckout-src
   mkdir zc-keys
   docker run --rm -v ${PWD}\zeccheckout-src:/src -v ${PWD}\zc-keys:/out -e CARGO_TARGET_DIR=/tmp/target -w /src rust:1.99.0-slim-bookworm cargo run --release --locked --bin zc-keygen -- /out/zc-testnet-seed.txt
   ```

   Keep the clone and `zc-keys` outside this repository and never commit the seed file.

2. **Fill in `.env`** (it is ignored by git): `PAYMENT_GATE=1`, `ZC_API_KEY` and
   `ZC_WEBHOOK_SECRET` (two different random values of 24+ characters), `ZC_UFVK` (the
   `uviewtest1...` key) and `ZC_URL=http://zeccheckout:10000`. If the viewing key is
   damaged when copied you will see `invalid UFVK ... not Bech32m encoded`; write it with
   PowerShell instead of an editor.

3. **Start it:** `docker compose --profile zec up --build`. ZecCheckout scans from the
   current chain tip, so start it *before* you pay. Do not run the `zec` and `fakepay`
   profiles together (both use port 8080).

4. **Pay.** Pass the age check, open `/members` (it sends you to `/pay`), copy the address
   shown there into your testnet wallet and send 0.001. The page moves from pending to
   detected to paid after about 3 confirmations (a few minutes on testnet) and then opens
   the members area.

If the site skips `/pay`, your browser may still hold an invoice from an earlier run that
the saved database remembers as paid. Use a private window or clear cookies for localhost.

## Let other people try it (temporary public address, test only)

`scripts/go-public.ps1` puts the Compose stack on a temporary public https address
through a free Cloudflare quick tunnel, so someone else can try the age check from their
own phone. Test credentials and testnet coins only.

1. Install cloudflared once: `winget install --id Cloudflare.cloudflared -e`, then open a
   new PowerShell window.
2. With the stack running (`docker compose -f docker-compose.yml -f docker-compose.fork.yml up -d`):

   ```
   powershell -ExecutionPolicy Bypass -File .\scripts\go-public.ps1
   ```

   It prints an address like `https://some-random-words.trycloudflare.com/verify`. It
   writes that address into the verifier's `expected_origin`, turns on secure cookies and
   `TRUST_PROXY` in `.env`, and restarts the site and verifier.
3. To stop: `powershell -ExecutionPolicy Bypass -File .\scripts\go-public.ps1 -Stop`.
   Everything goes back to `http://localhost:5000`.

The address changes every time the tunnel starts, and the site is only up while your
laptop is on. Cloudflare sees visitors' IP addresses and which pages they open; the site
itself keeps a visitor's address in memory for one minute, for rate limiting, and writes
no access log. `TRUST_PROXY=1` makes the site read the visitor's address from the
tunnel's `X-Forwarded-For` header; only use it when the site is reachable through that
one proxy (Compose binds it to 127.0.0.1, so it is).

## Prove age with a passport (ZKPassport, test only)

An optional second route: `/passport` shows a QR code (a link on a phone) for the
[ZKPassport](https://github.com/zkpassport/zkpassport-packages) app, which reads a passport's
chip and proves "18 or over". A small service in `passport/` checks the proofs on this
machine, never through ZKPassport's API. Details: [passport/README.md](passport/README.md).

1. In `.env`: `PASSPORT_URL=http://passport:8100` and keep `PASSPORT_DEV_MODE=1`.
2. Start it with the rest of the stack:

   ```
   docker compose -f docker-compose.yml -f docker-compose.fork.yml --profile passport up -d --build
   ```

3. Open `/passport` at the same address as `SITE_ORIGIN` (a proof made for `localhost`
   is refused when the site expects a tunnel address, and the other way round).
4. No passport needed for testing: [scripts/test-phone](scripts/test-phone/README.md) stands
   in for the app and proves from a mock passport.

What the site learns is only "18 or over": it drops the per-site identifier ZKPassport
proofs carry, so visits cannot be linked. Every visit gets its own random scope, which the
site accepts once and for 15 minutes, so a captured proof is refused on replay. To check the
whole route in one command (mock passports: an adult, a minor and two replays):

```
powershell -ExecutionPolicy Bypass -File .\scripts\e2e.ps1
```

Dev mode accepts only mock passports from the fictional "Zero Knowledge Republic". Keep it
on: ZKPassport says it has not had an external audit, and neither has this service. A
question to ZKPassport about the per-visit scope:
<https://github.com/zkpassport/zkpassport-packages/issues/385>.

## Known problems and open questions

- **Photo ID and mDL documents fail on the phone.** The verifier's proof circuit
  only fits a document whose signed data is small. In testing, a signed data block
  of about 2,500 bytes proved fine and about 2,560 bytes failed, so documents with a
  portrait or many fields are probably too large. The Age Verification document is
  small enough. The Multipaz test app's ZK-friendly mDL also failed for a separate
  reason (it carried key authorizations the circuit does not accept); that was fixed in
  the test app ([multipaz#2126](https://github.com/openwallet-foundation/multipaz/pull/2126))
  as a workaround until [longfellow-zk#220](https://github.com/longfellow-zk/longfellow-zk/issues/220).
  Not retested here since.
- **Wrong document type:** the verifier asks for `eu.europa.ec.av.1`. Other types
  give `claim-mismatch`.
- **Issuer trust is manual.** You must supply the right root certificate yourself.
  Only trust issuers you intend to trust, and never reuse the demo certificates on a
  real site.
- **Trust lists are not a safe shortcut.** The verifier's ETSI trust-list loader (as
  of version 0.4.0) takes every certificate it finds in the file, including the
  list's own signing certificates, and does not check the list's signature. The EU's
  example list inspected during testing contained only signing certificates, so by the
  loader's code, adding it would make those signers trust anchors (not tested
  that way). Prefer individual root certificates that you checked by hand.
- **`untrusted-issuer` carries no detail,** so finding the right root takes the
  debugging steps above.
  I reported this and the trust-list point to the verifier's maintainers:
  <https://github.com/pipe23-org/zk-age-verifier/issues/76>.
- **Windows:** the verifier's compiled dependency has no Windows build, which is
  why it runs in Docker instead of `pip install`.
- The Flask `secret_key` falls back to a placeholder unless `SECRET_KEY` is set.
  Compose requires it, and the payment step refuses to start with the placeholder.
  Always set a real one beyond a quick local test.

## Write-up

A plain-language account of what I built and what went wrong along the way: [docs/WRITEUP.md](docs/WRITEUP.md).

## Credits and licences

Built on open-source work by others: Google's
[Longfellow ZK](https://github.com/google/longfellow-zk), the
[pylongfellow](https://pypi.org/project/pylongfellow/) Python binding and
[zk-age-verifier](https://pypi.org/project/zk-age-verifier/) by pipe23-org, and
the Multipaz test app from the OpenWallet Foundation, the EU age verification
reference app, Zingo Labs' Zingo wallet, the Zcash Foundation's Zebra, and
[ZecCheckout](https://github.com/samizdatproject/zeccheckout) by Samizdat Project,
and [ZKPassport](https://github.com/zkpassport/zkpassport-packages) (Apache-2.0) for the
optional passport route.
This repository contains only glue code and scripts written while learning; none of
the above is included in it.

## Running the verifier from our fork

By default the stack uses upstream's published verifier image. To run the fork at https://github.com/Mirrorisor/zk-age-verifier instead (it logs which certificate was refused, issue #76):

    docker compose --profile zec -f docker-compose.yml -f docker-compose.fork.yml up --build

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

## Known problems and open questions

- **Photo ID and mDL documents fail on the phone.** The verifier's proof circuit
  only fits a document whose signed data is small. In testing, a signed data block
  of about 2,500 bytes proved fine and about 2,560 bytes failed, so documents with a
  portrait or many fields are probably too large. The Age Verification document is
  small enough.
- **Wrong document type:** the verifier asks for `eu.europa.ec.av.1`. Other types
  give `claim-mismatch`.
- **Issuer trust is manual.** You must supply the right root certificate yourself.
  Only trust issuers you intend to trust, and never reuse the demo certificates on a
  real site.
- **Windows:** the verifier's compiled dependency has no Windows build, which is
  why it runs in Docker instead of `pip install`.
- The Flask `secret_key` in `app.py` is a placeholder. Change it before using
  this for anything beyond a local demo.

## Credits and licences

Built on open-source work by others: Google's
[Longfellow ZK](https://github.com/google/longfellow-zk), the
[pylongfellow](https://pypi.org/project/pylongfellow/) Python binding and
[zk-age-verifier](https://pypi.org/project/zk-age-verifier/) by pipe23-org, and
the Multipaz test app from the OpenWallet Foundation. This repository contains
only glue code and scripts written while learning; none of the above is
included in it.

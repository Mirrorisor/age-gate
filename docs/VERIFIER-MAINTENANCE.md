# Maintaining the verifier fork

The site runs our fork of zk-age-verifier (https://github.com/Mirrorisor/zk-age-verifier),
because upstream has not responded to the fixes offered to it (see the README, "Which verifier
this uses"). This page is the routine that keeps the fork safe to depend on, and a log of each
time it was run. It is roadmap milestone M7.

## The routine (monthly, and whenever an advisory is announced)

In a checkout of the fork:

1. **Upstream changes.** `git fetch upstream` and `git log main..upstream/main`. Merge what is
   there, or note why not.
2. **Known vulnerabilities.** In Linux (the proof library has no Windows build):

   ```
   pip install uv pip-audit
   uv export --frozen --no-hashes --no-dev --no-emit-project > /tmp/r.txt
   pip-audit --no-deps --disable-pip -r /tmp/r.txt
   ```

   For each finding, `uv lock --upgrade-package <name>`. Also upgrade anything `uv lock`
   reports as yanked. Since 2026-11-19 the fork's `Audit` workflow runs this check, and a Trivy
   scan of the built image, on every push and weekly; look at its latest run first.
3. **Tests.** `uv sync --frozen` then `uv run --frozen pytest`. All must pass, with the
   required 100% coverage.
4. **Publish.** Push to the fork's `main`; its "Fork image" workflow publishes
   `ghcr.io/mirrorisor/zk-age-verifier:fork`.
5. **Pin.** In this repository, pull the new image, put its digest in `docker-compose.yml`, run
   the test suite and `scripts/e2e.ps1`, check one real phone wallet (the Multipaz Test App's
   Age Verification document) against it, and commit.
6. **Log it** below: date, what changed, why.

The site's own packages and the passport service's are audited by CI every week
(`.github/workflows/tests.yml`, the `audit` job), and the `images` job there scans the site and
passport images and reports on every pinned third-party image.

## Log

### 2026-11-19

- Upstream: nothing new since #78 (merged into the fork on 18 Nov).
- pip-audit: no known vulnerabilities in the fork's locked runtime dependencies.
- A first scan of the images (Trivy) found the fork image's only fixable high findings in the
  base image's setuptools (vendored jaraco.context 5.3.0, CVE-2026-23949; wheel 0.45.1,
  CVE-2026-24049). The runtime stage is now pinned to python:3.11-slim-bookworm 3.11.18 and
  removes pip, setuptools and wheel, which the service never uses: 0 findings after.
- New fork `Audit` workflow (pip-audit and Trivy, weekly and on every push).
- Published and pinned: fork commit 0739618; CI, Audit and "Fork image" passed;
  `docker-compose.yml` now pins `sha256:12edd64d...`.
- Same day in this repository: the site image moved to python:3.13-slim 3.13.18 without pip
  (its vendored msgpack, urllib3 and setuptools had advisories), the passport image to Bun
  1.4.5 (the 1.3.8 image's Debian packages had 74 fixable high or critical findings, and the
  1.3 line has had no image since May), Caddy to 2.11.9 (2.10.2 had a critical advisory),
  and lightwalletd and the optional upstream verifier to their current builds. Zebra 7.1.0 is
  the newest release and ZecCheckout has no newer image; their findings are reported weekly by
  the `images` job.

### 2026-10-30

- Upstream: nothing new since 2026-10-22 (only automatic dependency bumps, none merged since).
- pip-audit found five advisories in the fork's locked runtime dependencies:
  - anyio 4.14.1: CVE-2026-63374 (TLS host-name spoofing through IDNA 2003 encoding, network,
    high), CVE-2026-63349 and CVE-2026-64847 (local, process handling). Upgraded to 4.15.1.
  - certifi 2026.6.17: GHSA-6q48-6c7w-9gw2 (bundled emSign roots whose intermediate keys were
    compromised). Upgraded to 2026.10.23.
  - Not shown to be exploitable in the verifier; upgraded because the fixes are small.
- charset-normalizer 3.4.8 had been yanked; upgraded to 3.5.2.
- The fork's 289 tests pass with 100% coverage, and pip-audit finds nothing in the new lock.
- The site's packages and the passport service's packages: no known vulnerabilities.
- Published and pinned: fork commit 623ce86 pushed to its `main`; its CI and "Fork image"
  workflow passed; `docker-compose.yml` now pins image `sha256:57a33605...`. Checked: the
  verifier reports ref 623ce86 with anyio 4.15.1 and certifi 2026.10.23, `scripts/zkdemo.py`
  proves and verifies in the new image and rejects a false claim, and the site's 168 tests pass.
- Real phone, 2026-10-30 23:22 UTC: the Multipaz Test App's Age Verification document passed
  against the patched fork (`verify_succeeded` in 575 ms), then a shielded testnet payment
  through our own node was detected and marked paid.
- Second real wallet, 2026-10-30 23:41 UTC: the EU Age Verification reference app's credential
  (EU demo issuer) also passed against fork 623ce86 (`verify_succeeded` in 569 ms). Its log shows
  the expected `key_usage_der_fallback` warning: the EU demo root's issuer-alternative-name
  extension does not parse, and the verifier's DER fallback (upstream #33) reads its keyUsage.

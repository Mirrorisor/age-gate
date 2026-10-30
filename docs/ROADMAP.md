# Roadmap

Where the project stands and what funding would pay for. Each milestone ends in something a
reviewer can check, not just a promise. The gaps it starts from are in
[THREAT-MODEL.md](THREAT-MODEL.md).

## Done so far (October 2026, unfunded)

- A website that gates a page behind a zero-knowledge "over 18" check from a phone wallet,
  tested end to end with two wallets and two test issuers.
- An optional passport route (ZKPassport), mock passports only, with per-check binding against
  replay and a one-command end-to-end check (`scripts/e2e.ps1`).
- An optional shielded Zcash payment step, tested on testnet with a real wallet.
- A privacy audit in the test suite that fails if the site keeps more than `/privacy` says.
- Dependencies pinned, CI building every part, a written threat model.
- Shared state: invoices, used passport scopes and rate limits are kept in SQLite files, so they
  survive a restart and are shared by several workers (checked live with two gunicorn workers:
  exactly 30 of 35 requests got through, and the count survived a restart). Rate-limit rows
  hold a keyed hash of the address, never the address.
- Reusable gates for any Flask site, for the phone wallet (`AgeGate`) and the passport
  (`PassportGate`), sharing one pass, with instructions in `docs/REUSE.md`, an example site, and
  tests that mount them on a fresh Flask app in CI.
- A maintained fork of the verifier, with fixes found while building this (a log of which
  certificate was refused, a safer trust-list loader, `--check-cert`), which the stack runs by
  default.
- Upstream contributions: a merged fix to the Multipaz test app
  ([multipaz#2126](https://github.com/openwallet-foundation/multipaz/pull/2126)), two open pull
  requests and an issue on the verifier
  ([zk-age-verifier#76](https://github.com/pipe23-org/zk-age-verifier/issues/76)), and a docs
  question to ZKPassport ([#385](https://github.com/zkpassport/zkpassport-packages/issues/385)).

## Milestones

Numbers stay fixed: finished milestones (M3, M6) moved up to "Done so far".

### M1. External review

An independent security review of the site, the passport service and how they use the verifier
and ZecCheckout, against [THREAT-MODEL.md](THREAT-MODEL.md).

- **Deliverable:** the reviewer's report, published, and a fix or a written answer for every
  finding.
- **Done when:** every finding is closed or explained in the threat model.

### M2. Payments we can verify

ZecCheckout currently trusts a public lightwalletd it cannot check, so a hostile server could make
an unpaid invoice look paid (threat T8).

- **Deliverable:** the checkout reads the chain through a node we run (Zebra plus a lightwalletd
  or Zaino in front of it), in the same Compose setup.
- **Done when:** a testnet payment goes through with no public chain server in the path, shown by
  the container's configuration and logs.
- **Started:** `docker-compose.node.yml` now runs lightwalletd in front of our Zebra node, and
  ZecCheckout takes `ZC_LIGHTWALLETD`. Its first sync and a payment through it are still to do.

### M4. Larger credentials (driving licences, photo ID)

The verifier's proof circuit only fits small documents, so only the Age Verification document
works from a real wallet.

- **Deliverable:** a measured account of the size limit and, working with the verifier and
  Longfellow maintainers, either support for larger documents or a request shape that fits.
- **Done when:** an mDL from the Multipaz test app proves `age_over_18` through the site, or the
  limit and its cause are documented upstream.
- **Started:** the limit is measured and explained in [CREDENTIAL-SIZE.md](CREDENTIAL-SIZE.md):
  a 2,533-byte MSO, about 62 fields, decided by the number of fields and not their size. It also
  found a crash in Longfellow's C++ prover on nested fields, reported as
  [longfellow-zk#221](https://github.com/longfellow-zk/longfellow-zk/issues/221).

### M5. A careful real-credential pilot

Only after M1. Real passports (dev mode off) and a real mdoc issuer, with a small number of
consenting testers.

- **Deliverable:** a pilot report: what worked, what failed, what the site and its partners saw.
- **Done when:** the report is published and the privacy audit still passes with real credentials.

### M7. Keep the verifier maintained

The site depends on the zk-age-verifier service. Upstream shows little activity and has not
responded to the fixes offered to it, so this project runs and maintains its own fork
(https://github.com/Mirrorisor/zk-age-verifier).

- **Deliverable:** the fork kept current: upstream changes and security fixes brought over,
  dependencies updated, its tests and published image passing, and a short note per release on
  what changed and why.
- **Done when:** for the funded period, every upstream release and security advisory has been
  either merged into the fork or recorded as not applicable, and the stack is pinned to a fork
  image built from that state.
- **Started:** the routine and its log are in [VERIFIER-MAINTENANCE.md](VERIFIER-MAINTENANCE.md).
  The first run fixed five known vulnerabilities in the fork's dependencies, and CI now audits
  the site's and the passport service's packages every week.

## Not planned

Accounts, identity beyond "over 18", storing proofs, and anything on mainnet before M1 and M2
are done.

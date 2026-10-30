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
- Upstream contributions: a merged fix to the Multipaz test app
  ([multipaz#2126](https://github.com/openwallet-foundation/multipaz/pull/2126)), two open pull
  requests and an issue on the verifier
  ([zk-age-verifier#76](https://github.com/pipe23-org/zk-age-verifier/issues/76)), and a docs
  question to ZKPassport ([#385](https://github.com/zkpassport/zkpassport-packages/issues/385)).

## Milestones

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

### M3. State that survives restarts and more than one worker

Rate limits live in memory, in one process. (Used passport scopes already survive a restart:
they are kept in a SQLite file.)

- **Deliverable:** rate limits kept in shared storage, so the site can run more than one worker
  and a restart resets nothing.
- **Done when:** tests show rate limits hold across a restart and across two workers.

### M4. Larger credentials (driving licences, photo ID)

The verifier's proof circuit only fits small documents, so only the Age Verification document
works from a real wallet.

- **Deliverable:** a measured account of the size limit and, working with the verifier and
  Longfellow maintainers, either support for larger documents or a request shape that fits.
- **Done when:** an mDL from the Multipaz test app proves `age_over_18` through the site, or the
  limit and its cause are documented upstream.

### M5. A careful real-credential pilot

Only after M1. Real passports (dev mode off) and a real mdoc issuer, with a small number of
consenting testers.

- **Deliverable:** a pilot report: what worked, what failed, what the site and its partners saw.
- **Done when:** the report is published and the privacy audit still passes with real credentials.

### M6. Something others can reuse

- **Deliverable:** the passport check packaged like the existing Flask age-check module, with
  instructions for adding both to an existing site.
- **Done when:** a fresh Flask app gains the age gate by following the instructions, checked in CI.

## Not planned

Accounts, identity beyond "over 18", storing proofs, and anything on mainnet before M1 and M2
are done.

# Roadmap

Where the project stands and what funding would pay for. Each milestone ends in something a
reviewer can check, not just a promise. The gaps it starts from are in
[THREAT-MODEL.md](THREAT-MODEL.md).

## The goal

An open-source, privacy-first **age-verification toolkit that any site can run itself**: a
visitor proves "18 or over" with whatever credential they have, the site learns nothing else,
and no central party learns who verified or where.

A toolkit rather than a hosted service, on purpose. Each site runs its own copy, so there is no
middleman who sees every check, and the project publishes software rather than handling other
people's visitors. A hosted option could come later if sites ask for one; it would need its own
design and its own review.

The order matters: an independent review (M1) and a careful real-credential pilot (M5) come
before any of the toolkit milestones (M8 to M11) are offered for real use.

## Done so far (October 2026, unfunded)

- A website that gates a page behind a zero-knowledge "over 18" check from a phone wallet,
  tested end to end with two wallets and two test issuers.
- An optional passport route (ZKPassport), mock passports only, with per-check binding against
  replay and a one-command end-to-end check (`scripts/e2e.ps1`).
- An optional shielded Zcash payment step, tested on testnet with a real wallet.
- A privacy audit in the test suite that fails if the site keeps more than `/privacy` says.
- Dependencies pinned, CI building every part, a written threat model, and an internal
  self-review against it (38 attacks on the running stack, three low findings fixed): [SELF-REVIEW.md](SELF-REVIEW.md).
- Payments we can verify: ZecCheckout reads the chain through our own Zebra node and lightwalletd
  (`docker-compose.node.yml`, `ZC_LIGHTWALLETD`). Tested 2026-10-30: with `ZC_LIGHTWALLETD` pointing at our node, a 0.001 TAZ shielded payment from Zingo was detected and marked paid, and the site recorded it, with no public chain server in the path.
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

Numbers stay fixed: finished milestones (M2, M3, M6) moved up to "Done so far".

### M1. External review

An independent security review of the site, the passport service and how they use the verifier
and ZecCheckout, against [THREAT-MODEL.md](THREAT-MODEL.md).

- **Deliverable:** the reviewer's report, published, and a fix or a written answer for every
  finding.
- **Done when:** every finding is closed or explained in the threat model.

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

### M8. More ways to prove age, and to plug it in

Not everyone has a passport or a wallet credential, and not every site is built on Flask.

- **Deliverable:** a small standalone verification service with a documented HTTP interface, so
  a site in any language can use it, alongside the Flask gates; and a clear way to add a new
  credential type next to the phone wallet and passport routes.
- **Done when:** a non-Flask example site (for example a few lines of Node or PHP) passes the
  same end-to-end checks in CI, and adding a credential type is documented with a worked example.
- **Built (2026-10-31):** `agecheck.service` with a signed-token handoff, a Node example site with
  no dependencies, `docs/SERVICE.md` (the interface, and how to add a credential type, with
  `PassportGate` as the worked example), 24 unit tests, and `scripts/test-phone/e2e-handoff.ts`,
  which passed live: an adult goes from the Node site through the service and back in; a reused,
  stolen or tampered token is refused; a minor gets no token. Added to the e2e CI workflow.

### M9. Standards alignment

Sites will ask whether the toolkit meets the frameworks that apply to them.

- **Deliverable:** a written comparison against the published standards and frameworks the
  toolkit touches (the EU age-verification blueprint, ISO/IEC 18013-5 and -7 for mdoc, and the
  Australian online-safety requirements in force at the time), listing what is met, what is not,
  and what would be needed. Reviewed by someone qualified where it touches law.
- **Done when:** the comparison is published, and every gap it finds is either closed or listed
  in the threat model.

### M10. Trusted issuer lists

Today each site trusts whatever certificates are in a folder, set up by hand.

- **Deliverable:** a maintained, checked list of the issuers a site may choose to trust, with a
  tool to fetch and verify it (building on the fork's pinned, service-only trust-list loading),
  and clear guidance on choosing issuers.
- **Done when:** a fresh install can trust a real issuer by following the guide, with the list's
  integrity checked, and the guide says plainly what trusting an issuer means.

### M11. A path for people without a supported credential

- **Deliverable:** guidance and hooks for sites to offer another method to people who cannot use
  the zero-knowledge routes, without the toolkit itself collecting identity documents.
- **Done when:** the docs and the gates show how a site adds such a path, and the privacy page
  explains which route a visitor took and what each route reveals.

## Not planned

Accounts, identity beyond "over 18", storing proofs, collecting identity documents, a hosted
service before the toolkit is reviewed, and anything on mainnet before M1 and M2 are done.

# Self-review, 2026-10-30

**This is an internal review, not an independent audit.** It was done by the people who built
the project, so it shares their blind spots. Its purpose is to find and fix what we can before an
outside reviewer looks, so their time goes on the hard problems. The threat it follows is
[THREAT-MODEL.md](THREAT-MODEL.md).

Method: for each threat, actively try to break the running system, not only read the code. Every
attack below was run against the live Docker stack (site, verifier fork 623ce86, passport
service, ZecCheckout) unless it says otherwise. The scripts are in `scripts/` so anyone can
re-run them.

## Summary

| | Count |
|---|---|
| Attacks on the running stack (site 18, passport service 13 + 7 with a real proof) | 38 |
| Resisted on the first try | 37 (the exception is F3) |
| Exposure checks (ports, users, secrets, git history, dependencies) | all clean |
| Findings fixed in this review | 3, all low (F1 and F2 found by reading the code, F3 by attack) |
| Earlier findings fixed today, before this review | 5 |
| Not covered (see the end) | 6 areas |

No finding let anyone in without a valid proof, forge a payment, or read personal data.

## Findings fixed in this review

### F1. Every `<script>` in a page was given the CSP nonce (low, defence in depth)

The site added its per-request script nonce by rewriting every `<script>` tag in its HTML output.
Nothing reflects visitor input today (checked below), but if a future change ever did, an injected
`<script>` would have been handed a valid nonce and run despite the Content-Security-Policy.

Fix: pages write the nonce into their own script tags (`with_nonce` in `app.py`); nothing rewrites
the output. Test: `test_markup_that_reaches_a_page_another_way_gets_no_nonce` (fails on the old
code).

### F2. The reusable gates allowed a tab in the "next" redirect (low)

After a visitor passes, `AgeGate` and `PassportGate` send them back to the page they wanted. They
refused targets starting with `//` but allowed control characters such as a tab. Browsers drop
tabs from URLs, so `/<tab>/evil.example` becomes `//evil.example`, another site. The target comes
from the path of a protected page, so it is reachable only on a site that protects a catch-all
route, but a library should be safe for whoever uses it.

Fix: any control character or backslash anywhere in the target is refused (`Gate._safe_next`).
Tests: five new cases in `test_the_gate_never_redirects_to_another_site` (four fail on the old
code; the `\r` case was already refused) and `test_ordinary_paths_with_queries_are_still_allowed`.

### F3. A proof set with a piece repeated was accepted (low)

A ZKPassport proof is a set of pieces, each stating its place (`index`) and the set's size
(`total`). Appending a copy of one piece to a valid set still passed ZKPassport's SDK check. No way
to exploit it was found: the copy proves the same claim, for the same person, under the same
single-use scope. But the service accepted a set the app never sent.

Fix: `passport/check.ts` refuses any set that is not pieces `0..total-1`, each once, with `total`
equal to the set's real size. Checked with a real proof: the repeated set is now refused, and the
untouched valid set is still accepted.

## Earlier findings, fixed today before this review

- Resending an old session cookie gave a used passport check a second try (scope record moved to
  the server).
- Visiting `/passport` set a cookie, against the privacy promise (scope now made on Start).
- Moving rate limits to disk would have written raw IP addresses (now a keyed hash, rows
  overwritten on delete).
- Five known vulnerabilities in the verifier fork's dependencies (anyio, certifi), published and
  pinned. See [VERIFIER-MAINTENANCE.md](VERIFIER-MAINTENANCE.md).
- The README blamed portraits for large credentials failing; measured, it is the number of fields
  ([CREDENTIAL-SIZE.md](CREDENTIAL-SIZE.md)).

## What was tried, and held

### The site (`scripts/self_review_probes.py`: 18 of 18)

| Attack | Result |
|---|---|
| Session cookie signed with a wrong key, unsigned, or signed with the old placeholder key | refused (redirected to the gate) |
| Cookie flags | `HttpOnly`, `SameSite=Lax` |
| 35 requests, each with a different spoofed `X-Forwarded-For` | limited after 30: the header is ignored while `TRUST_PROXY` is off |
| 70 KB body on an ordinary route; 9 MB passport upload | 413 |
| Security headers on 404, 405 and 413 responses | present (CSP, `X-Frame-Options`, etc.) |
| `<script>` in query strings and paths of every public page | never reflected |
| "Paid" webhook unsigned, signed with a wrong secret, or correctly signed but 10 minutes old | refused (400) |
| Correctly signed "paid" webhook for an invoice the checkout does not know | ignored: the site asks ZecCheckout and gets no confirmation |
| ZecCheckout's API without its key | 401 |
| Passport service from outside Docker | not reachable |

### The passport service, with made-up input (13 of 13)

Missing scope, wrong prefix, a 500-character scope, no proofs, proofs that are not a list, a result
claiming age >= 17, a result saying false, a result with an extra disclosed field (nationality), a
result that is not an object, garbage proof objects: all refused with `ok: false`. Malformed JSON:
400. A 9 MB body: 413. The service stayed healthy throughout.

### The passport service, with a real proof (`scripts/self_review_tamper.py`: 7 of 7 after F3)

| Change to a real, valid mock-passport proof | Result |
|---|---|
| None (sanity check) | accepted |
| Presented for another domain | refused |
| Presented under another scope | refused |
| One character of a proof changed | refused |
| Last piece removed | refused |
| A piece repeated | refused (accepted before F3) |
| Sent to a copy of the service with dev mode off | refused: "You are trying to verify a mock proof. This is only allowed in dev mode." |

### Exposure and secrets

- Published ports: only on 127.0.0.1 (site 5000, verifier 8000, ZecCheckout 8080, lightwalletd
  9067). The passport service and Zebra's RPC are not published at all.
- Every container runs as a non-root user (`appuser`, `bun`, `app`, `nonroot`).
- `.env` has never been committed, and none of its secrets appears anywhere in git history.
- Dependencies: no known vulnerabilities in the site's or the passport service's packages; the
  verifier fork's are fixed (see above). CI audits them weekly.

## Accepted, and why

- **`/logout` is a link (GET).** Another site could log a visitor out by linking to it. That costs
  the visitor a re-check, nothing more.
- **`/health` shows the verifier's version.** Useful for running the site; the version is public
  in the fork anyway.
- **The verifier has an unauthenticated `/debug/transcript` route.** It is published only on
  127.0.0.1, so only this machine can reach it.
- **The passport route depends on ZKPassport's relay.** If it drops a message, the check times out;
  it does not let anyone in.
- **Payments trust a public lightwalletd unless `ZC_LIGHTWALLETD` is set.** Since this review a
  payment through our own node has been tested (threat T8, roadmap M2); the public server remains
  the fallback when the setting is empty.

## Not covered

1. **The cryptography itself:** Longfellow's and ZKPassport's circuits and proof systems are
   trusted as published.
2. **Tampering with real mdoc (phone wallet) proofs:** only the passport proofs were tampered
   with; the mdoc route relies on the verifier's own tests and design.
3. **The browser side:** `passport/client.ts` and the wallet page script were reviewed by reading,
   not attacked in a browser.
4. **Denial of service at scale:** only single oversized requests and the rate limit were tried.
5. **ZecCheckout, Zebra and lightwalletd internals:** used as published.
6. **Real passports and real government-issued credentials:** not tested, on purpose (dev mode).

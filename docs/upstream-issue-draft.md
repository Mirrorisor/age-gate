# DRAFT, not posted. For zkpassport/zkpassport-packages (public issue, a docs question, not a vulnerability)

## Title

Docs: is using `scope` as a per-visit challenge supported? (binding a proof to one session)

## Body

I run a small age gate (https://github.com/Mirrorisor/age-gate) that checks "18 or over" proofs server side
with `verifierMode: "local"` and the SDK at 0.19.2.

The SDK README describes `scope` as tying the unique identifier to a use case. My gate drops the
identifier on purpose (an age gate has no use for it, and keeping it would let visits be linked), so I
cannot use the "store the identifier with a uniqueness constraint" pattern to spot a reused proof.

What I did instead: each visit to the passport page gets a new random scope, `age-over-18:<random>`.
The page passes it to `request()`, the server remembers it in the session, and the same value goes to
`verify()`. I tested it with the headless app from `packages/e2e` and a mock passport (dev mode):

- a proof made for scope A and submitted with scope A: verified;
- the same proofs submitted with scope B: refused, with
  "The proof uses a different scope than the one expected".

Questions:

1. Is this a supported use of `scope`, or could a later release change how scope is checked or hashed?
   Is there a length or character limit I should keep to? (I used 34 characters and did not
   hit one.)
2. If it is fine, could the docs say so? Anyone who does not store the identifier has no other way to
   tie a proof to one visit, and the README does not mention it.
3. Apart from scope, is there anything in a proof that limits how long it stays valid (for example a
   date window)? I did not test this, so I do not know how long a captured proof stays usable without
   a per-visit scope.

Not claiming a bug: I only tested dev mode with mock passports, and I have not read how scope is hashed
into the circuit.

## Checks before posting (do not paste this part)

- Verified by me: scope mismatch is refused (live, passport service log); same-session reuse is refused
  by my own site, not by the SDK.
- Checked against the SDK README (packages/zkpassport-sdk/README.md, main branch, 2026-10-30): scope is
  described only as tying the unique identifier to a use case (default: your domain only); the
  "Verifying the proofs" section says to store the identifier with a uniqueness constraint; the README
  does not mention a length limit for scope, or any proof expiry or freshness. Re-check the README at
  posting time, and compare with the version you run (0.19.2).
- Not verified: how the proof's date window works, how long a scope may be, whether the pre-fix replay
  would really have been accepted (I never ran that case).
- Posting publicly is your call and happens under your GitHub account.

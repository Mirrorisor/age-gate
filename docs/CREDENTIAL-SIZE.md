# Why larger credentials fail (roadmap M4)

Only the small EU Age Verification document works from a real wallet; driving licences (mDL)
and photo IDs fail. This is the measured account of why. Measured 2026-10-30 with
`scripts/measure_mso_limit.py`, inside the verifier fork's image (pylongfellow 0.5.2, the
version 7 one-attribute Longfellow circuit the verifier pins).

## The limit

The proof circuit hashes the issuer-signed MSO (the "mobile security object": the list of
digests the issuer signs) inside the proof, and the circuit is compiled for a fixed number of
SHA-256 blocks. In Longfellow's source (`lib/circuits/mdoc/mdoc_constants.h`):

    kMaxSHABlocks = 40          // v7 circuits use 40, earlier ones use 35
    kMaxMsoLen    = kMaxSHABlocks * 64 - 9 - kCose1PrefixLen   // = 2560 - 9 - 18 = 2533 bytes

A credential whose tagged MSO is longer than 2,533 bytes cannot be proved with this circuit.

## What decides the MSO's size

| Credential (fake, built by pylongfellow's test helper) | MSO | Result |
|---|---|---|
| 62 fields, including `age_over_18` | 2,522 bytes | proves |
| 63 fields | 2,558 bytes | fails: `MDOC_PROVER_TAGGED_MSO_TOO_BIG` |
| 62 fields, one of them a 60 KB portrait | 2,522 bytes | proves |

- **The number of fields decides it, not their size.** The MSO holds one 32-byte digest per
  field, about 36 bytes each with its encoding, whatever the field contains. A portrait costs
  the same as a one-letter field.
- So the practical limit is **about 62 fields per credential**, minus whatever the issuer adds
  around the digests (validity dates, the device key, key authorizations). Real mDLs often carry
  more fields than that, across two namespaces. The Age Verification document carries few.
- The request cannot work around it: the issuer signs digests for every field in the credential,
  and the circuit must hash the whole MSO even to reveal one field.

## A second, separate problem: nested fields crash the C++ prover

| Credential | Prover backend | Result |
|---|---|---|
| `age_over_18` plus a nested `driving_privileges` (a list of maps, as in a real mDL) | `google-cpp` | **the process crashes** (segmentation fault, after "valueLength called on non-value type") |
| the same credential | `isrg-rust` | proves |

- The crash is in proving, which runs in the wallet, not in the verifier. Handed a garbage proof,
  the verifier's side raised a clean `VerifierError` (one input, not an exhaustive test).
- It is a bug in Longfellow's C++ prover, not a size limit: the Rust backend handles the same
  credential. Reported upstream as
  [longfellow-zk#221](https://github.com/longfellow-zk/longfellow-zk/issues/221).

## What would make larger credentials work

1. **Issuers keep age credentials small.** That is the approach the EU Age Verification document
   takes, and it already works here. It needs nothing from this project.
2. **A circuit compiled for more SHA blocks.** Longfellow already raised the limit once (35 to 40
   blocks for v7). A larger circuit means bigger proofs and slower proving, and the wallet and the
   verifier must both use the same circuit, so it needs Longfellow, wallet makers and verifier
   maintainers to agree. This project can ask, not decide.
3. **Fix the C++ prover crash** upstream, so mDLs with nested fields at least fail cleanly, or
   prove when they fit. Reported as [longfellow-zk#221](https://github.com/longfellow-zk/longfellow-zk/issues/221).

## Reproduce

    docker run --rm -v "%CD%\scripts:/demo" --entrypoint /app/.venv/bin/python ^
        ghcr.io/mirrorisor/zk-age-verifier:fork -u /demo/measure_mso_limit.py

The script stops when it reaches the nested-field case, because the C++ prover crashes the
process; the size results print before that.

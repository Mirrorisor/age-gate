# Why larger credentials fail (roadmap M4)

Full-size driving licences (mDL) and photo IDs fail from a real wallet, while the EU Age
Verification document and the Multipaz test app's reduced "ZKP-friendly" licence and Photo ID
work. This is the measured account of why. First measured 2026-10-30 with
`scripts/measure_mso_limit.py` inside the verifier fork's image (pylongfellow 0.5.2), and
measured again on 2026-11-19 with the fork build the stack now pins (pylongfellow 0.8.0): the
same version 7 one-attribute circuit, the same limit, and the same results, except the nested
field below.

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

## Fixed since: nested fields crashed the C++ prover

| Credential | Prover backend | 2026-10-30 (pylongfellow 0.5.2) | 2026-11-19 (pylongfellow 0.8.0) |
|---|---|---|---|
| `age_over_18` plus a nested `driving_privileges` (a list of maps, as in a real mDL) | `google-cpp` | **the process crashed** (segmentation fault, after "valueLength called on non-value type") | proves (MSO 383 bytes) |

- The crash was in proving, which runs in the wallet, not in the verifier. Reported as
  [longfellow-zk#221](https://github.com/longfellow-zk/longfellow-zk/issues/221) and
  [pylongfellow#82](https://github.com/pipe23-org/pylongfellow/issues/82); pylongfellow 0.8.0
  fixed it. A wallet still needs a prover with the fix.

## Also refused: key authorizations

The circuit requires the MSO's `deviceKeyInfo` to hold only the device key. The Multipaz test
app's normal documents also sign `keyAuthorizations` into it, and the phone's prover then fails
whatever the size. The ZKP-friendly test documents are issued without them
([multipaz#2126](https://github.com/openwallet-foundation/multipaz/pull/2126)), as a workaround
until [longfellow-zk#220](https://github.com/longfellow-zk/longfellow-zk/issues/220).

## What would make larger credentials work

1. **Issuers keep age credentials small.** That is the approach the EU Age Verification document
   takes, and it already works here. It needs nothing from this project.
2. **A circuit compiled for more SHA blocks.** Longfellow already raised the limit once (35 to 40
   blocks for v7). A larger circuit means bigger proofs and slower proving, and the wallet and the
   verifier must both use the same circuit, so it needs Longfellow, wallet makers and verifier
   maintainers to agree. This project can ask, not decide: asked in
   [longfellow-zk#228](https://github.com/longfellow-zk/longfellow-zk/issues/228) (44 blocks would
   fit 69 fields, 48 would fit 76).
3. **Issuers leave out key authorizations** for credentials meant for zero-knowledge proofs, or
   Longfellow accepts them ([longfellow-zk#220](https://github.com/longfellow-zk/longfellow-zk/issues/220)).

## Reproduce

    docker run --rm -v "%CD%\scripts:/demo" --entrypoint /app/.venv/bin/python ^
        ghcr.io/mirrorisor/zk-age-verifier:fork -u /demo/measure_mso_limit.py

It loads the circuit the same way the verifier does at startup. With pylongfellow 0.8.0 it runs
to the end (before 0.8.0 it stopped at the nested-field case, where the prover crashed).

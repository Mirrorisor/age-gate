"""Measure where the verifier's proof circuit stops fitting a credential (roadmap M4).

Builds fake mdoc credentials with pylongfellow's test helpers, tries to prove age_over_18
with the circuit the verifier pins, and reports the issuer-signed MSO size for each.
Run it inside the verifier's container, which has the library and the circuit:

    docker run --rm -v "%CD%\\scripts:/demo" --entrypoint /app/.venv/bin/python \
        ghcr.io/mirrorisor/zk-age-verifier:fork /demo/measure_mso_limit.py
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cbor2
from pylongfellow import Pylongfellow, mdoc
from pylongfellow.mdoc import testing

CIRCUITS = Path("/app/src/zk_age_verifier/circuits")
meta = json.loads((CIRCUITS / "v7-1attr.json").read_text())
spec = mdoc.CircuitSpec(
    system=meta["system"],
    circuit_hash=meta["circuit_id"],
    num_attributes=meta["num_attributes"],
    version=meta["version"],
    block_enc_hash=meta["block_enc_hash"],
    block_enc_sig=meta["block_enc_sig"],
)
client = Pylongfellow(backend="google-cpp")
client.load_circuit(spec, (CIRCUITS / "v7-1attr.circuit").read_bytes())

DOCTYPE = "org.iso.18013.5.1.mDL"
NS = "org.iso.18013.5.1"
NOW = datetime.now(timezone.utc)
TRANSCRIPT = cbor2.dumps([None, None, ["measure", "handover"]])
CLAIMS = [mdoc.RequestedAttribute(NS, "age_over_18", cbor2.dumps(True))]


def mso_size(document_bytes):
    """Bytes of the issuer-signed payload (the tagged MSO) inside a DeviceResponse."""
    response = cbor2.loads(document_bytes)
    issuer_auth = response["documents"][0]["issuerSigned"]["issuerAuth"]
    return len(issuer_auth[2])


def attempt(fields):
    """Make a credential with these fields (plus age_over_18) and try to prove. Returns (size, ok, error)."""
    elements = {"age_over_18": True, **fields}
    specimen = testing.create_presentation(
        DOCTYPE, {NS: elements}, TRANSCRIPT, NOW - timedelta(days=1), NOW + timedelta(days=30)
    )
    size = mso_size(specimen.mdoc)
    try:
        proof = client.prove(specimen.mdoc, specimen.issuer_public_key, TRANSCRIPT, CLAIMS, NOW)
        client.verify(specimen.issuer_public_key, TRANSCRIPT, CLAIMS, NOW, proof, DOCTYPE)
        return size, True, ""
    except Exception as exc:  # the library raises its own error types; we only report them
        return size, False, f"{type(exc).__name__}: {exc}"[:90]


def plain(count):
    """count short text fields (realistic for names, dates, codes)."""
    return {f"field_{i:03d}": "x" for i in range(count)}


print(f"Circuit: version {meta['version']}, {meta['num_attributes']} attribute")
print("Limit in Longfellow's source: kMaxMsoLen = 40 * 64 - 9 - 18 = 2533 bytes\n")

# 1. Find the largest number of plain fields that still proves (binary search).
low, high = 0, 200
while low < high:
    mid = (low + high + 1) // 2
    if attempt(plain(mid))[1]:
        low = mid
    else:
        high = mid - 1
for count in (low, low + 1):
    size, ok, error = attempt(plain(count))
    print(f"{count + 1:3d} fields (incl. age_over_18): MSO {size} bytes -> {'PROVES' if ok else 'FAILS ' + error}")

# 2. Does a large field (a portrait) change the limit? Same count, one value made huge.
fits = plain(low)
fits["portrait"] = fits.pop(next(iter(fits)))  # keep the count the same
fits["portrait"] = b"\xff" * 60_000
size, ok, error = attempt(fits)
print(f"\nSame {low + 1} fields, one of them a 60 KB portrait: MSO {size} bytes -> "
      f"{'PROVES' if ok else 'FAILS ' + error}")

# 3. A nested field, like an mDL's driving_privileges.
nested = {"driving_privileges": [{"vehicle_category_code": "B", "issue_date": "2020-01-01"}]}
size, ok, error = attempt(nested)
print(f"Two fields, one nested (driving_privileges): MSO {size} bytes -> "
      f"{'PROVES' if ok else 'FAILS ' + error}")

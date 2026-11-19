import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import cbor2
from cryptography.hazmat.primitives import serialization
from pylongfellow import mdoc
from pylongfellow.mdoc import testing

from zk_age_verifier.core.engine.circuits import load_held_circuit

now = datetime.now(timezone.utc)
doctype = "org.iso.18013.5.1.mDL"
ns = "org.iso.18013.5.1"
transcript = cbor2.dumps([None, None, ["demo", "handover"]])

print("1. Making a fake credential...")
specimen = testing.create_presentation(
    doctype, {ns: {"age_over_18": True}}, transcript,
    now - timedelta(days=1), now + timedelta(days=30),
)
cert = specimen.issuer_certificate
print("   issuer certificate:", cert.subject.rfc4514_string())
try:
    Path("/demo/issuer.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("   saved issuer.pem")
except Exception as e:
    print("   could not save issuer.pem:", e)

print("2. Loading the circuit...")
# The verifier loads, checks and holds its pinned circuit the same way at startup.
held = load_held_circuit(backend="google-cpp")
client = held.longfellow
claims = [mdoc.RequestedAttribute(ns, "age_over_18", cbor2.dumps(True))]

print("3. Proving (may take a few seconds)...")
t0 = time.time()
proof = client.prove(specimen.mdoc, specimen.issuer_public_key, transcript, claims, now)
print(f"   proof made: {len(proof)} bytes in {time.time() - t0:.1f}s")

print("4. Verifying the proof...")
client.verify(specimen.issuer_public_key, transcript, claims, now, proof, doctype)
print("   VERIFIED: proof accepted")

print("5. Sanity check: a false claim must fail...")
bad = [mdoc.RequestedAttribute(ns, "age_over_18", cbor2.dumps(False))]
try:
    client.verify(specimen.issuer_public_key, transcript, bad, now, proof, doctype)
    print("   UNEXPECTED: false claim was accepted")
except Exception as e:  # the library's own error type
    print("   correctly rejected:", type(e).__name__)

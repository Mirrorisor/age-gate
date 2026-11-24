"""Trust the EU's official TEST age-verification issuers, and never a real one.

The EU publishes two signed Age Verification Trusted Lists: the acceptance list, with test
issuers from several Member States, and the production list, with real issuers. This script:

1. fetches both and checks each list's XML signature against signer certificates pinned
   below (the acceptance list's "TEST European Commission" certificate; for the production
   list, the six EU list-signing certificates named in it as of 2026-11-15);
2. refuses either list if it is past its NextUpdate;
3. takes the active age-attestation services of the acceptance list, drops every
   certificate that is also on the production list (a real issuer must never be trusted
   here: the acceptance list of 2026-11-15 carries one Danish production issuer), and
   drops certificates that are not valid today;
4. replaces the files named eu-av-test-*.pem in OUT_DIR with the remaining certificates and
   prints what it kept and what it left out. No other file in OUT_DIR is touched.

It runs inside the verifier fork's image, which has the same list code the verifier uses
(scripts/eu-test-issuers.ps1 does this). Restart the verifier afterwards.

Usage:
    python eu_test_issuers.py OUT_DIR [--acceptance LOCATION] [--production LOCATION]
                                      [--dry-run]

Exit status: 0 written (or would be, with --dry-run), 1 a list was refused (signature,
signer, NextUpdate), 2 bad usage or a list could not be read.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding

from zk_age_verifier.config import ConfigError
from zk_age_verifier.core.trustlist import (
    _check_next_update,
    _fetch,
    _service_anchors,
    _verified_list,
)

ACCEPTANCE = "https://acceptance.trust.tech.ec.europa.eu/lists/age-verification/av-tl.xml"
PRODUCTION = "https://trust.tech.ec.europa.eu/lists/age-verification/av-tl.xml"

# SHA-256 of the certificate that signs the acceptance list ("TEST European Commission",
# valid to 2028-11-20), read from the list of 2026-11-15.
ACCEPTANCE_SIGNERS = {"0ccf87a5abf4db89bde4e10202e2523296bea7d835ba6a5a41054b9e1e6b8949"}
# SHA-256 of the six certificates the production list of 2026-11-15 names as list signers
# (PointersToOtherTSL); the list was signed by e0a620fb...
PRODUCTION_SIGNERS = {
    "d2064fdd70f6982dcc516b86d9d5c56aea939417c624b2e478c0b29de54f8474",
    "e0a620fbb6747362bb933ac44169d676a553444716cf5f31605f12a22b8396b1",
    "c0641c4f7d56c431b1c924742db7fce9c1eef7d7fd212113a2768486b3abcdc5",
    "df7e29360c34b2b8d6d5f40325c1d4d12c9922cecd33b7407674a74b2b3ca1e5",
    "b63d416744e7098bf9ec2caa596a93bc2468e37f8284ba65ecc061711bcbaa18",
    "236103f03a8031ae8f47f9059bf8de38564cdbfebedde4a597d50f8980aa653b",
}
PREFIX = "eu-av-test-"


class Refused(Exception):
    """A list failed a check; nothing is written."""


def sha256(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def signature_certificate(data: bytes) -> x509.Certificate:
    """The certificate carried in the list's own enveloped signature."""
    root = ElementTree.fromstring(data)
    for signature in root:
        if local(signature.tag) != "Signature":
            continue
        for element in signature.iter():
            if local(element.tag) == "X509Certificate" and element.text:
                der = base64.b64decode("".join(element.text.split()))
                return x509.load_der_x509_certificate(der)
    raise Refused("the list carries no signer certificate in its signature")


def sequence_number(root: ElementTree.Element) -> str:
    for element in root.iter():
        if local(element.tag) == "TSLSequenceNumber":
            return (element.text or "").strip()
    return "?"


def checked_list(location: str, pinned: set[str], label: str) -> ElementTree.Element:
    """Fetch a list, require a pinned signer and a valid signature, refuse it if stale."""
    data = _fetch(location)
    signer = signature_certificate(data)
    if sha256(signer) not in pinned:
        raise Refused(
            f"{label} list is signed by {signer.subject.rfc4514_string()} "
            f"(SHA-256 {sha256(signer)}), which is not a pinned signer. The EU may have "
            "changed its signing certificate: check it, then update this script."
        )
    try:
        root = _verified_list(data, [signer], location)
        _check_next_update(root, location)
    except ConfigError as exc:
        raise Refused(f"{label} list: {exc}") from exc
    print(f"{label} list: signature ok (signer {sha256(signer)[:16]}), "
          f"sequence {sequence_number(root)}")
    return root


def slug(cert: x509.Certificate) -> str:
    names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    countries = cert.subject.get_attributes_for_oid(x509.NameOID.COUNTRY_NAME)
    country = str(countries[0].value) if countries else "xx"
    name = str(names[0].value) if names else "issuer"
    text = f"{country}-{name}".lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:48]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--acceptance", default=ACCEPTANCE)
    parser.add_argument("--production", default=PRODUCTION)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.out_dir.is_dir():
        print(f"{args.out_dir} is not a folder", file=sys.stderr)
        return 2

    try:
        acceptance = checked_list(args.acceptance, ACCEPTANCE_SIGNERS, "Acceptance (test)")
        production = checked_list(args.production, PRODUCTION_SIGNERS, "Production (real)")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"Cannot read a list: {exc}", file=sys.stderr)
        return 2

    real = {sha256(cert) for cert in _service_anchors(production)}
    now = datetime.now(timezone.utc)
    keep: list[x509.Certificate] = []
    seen: set[str] = set()
    for cert in _service_anchors(acceptance):
        fingerprint = sha256(cert)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        label = f"{cert.subject.rfc4514_string()[:70]} ({fingerprint[:16]})"
        if fingerprint in real:
            print(f"  left out, also on the production list: {label}")
        elif not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            print(f"  left out, not valid today (to {cert.not_valid_after_utc.date()}): {label}")
        else:
            keep.append(cert)
            print(f"  kept, valid to {cert.not_valid_after_utc.date()}: {label}")

    if not keep:
        print("REFUSED: no test issuer is left; nothing written", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"Dry run: would write {len(keep)} certificates to {args.out_dir}")
        return 0
    for old in args.out_dir.glob(f"{PREFIX}*.pem"):
        old.unlink()
    for cert in keep:
        name = f"{PREFIX}{slug(cert)}-{sha256(cert)[:8]}.pem"
        (args.out_dir / name).write_bytes(cert.public_bytes(Encoding.PEM))
    print(f"Wrote {len(keep)} certificates to {args.out_dir} as {PREFIX}*.pem. "
          "Restart the verifier to use them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

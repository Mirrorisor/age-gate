"""List and sanity-check the trust anchors in a verifier certs folder.

Usage:
    python scripts/trustlist.py [folder]

The folder defaults to verifier-config/certs. Only PEM files (.pem, .crt, .cer)
are read. Exit status is 0 when every certificate is usable, 1 when any is
expired, not yet valid, unreadable, or when the folder holds none.

Read-only: this script never changes or copies a certificate.
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

SOON_DAYS = 30
DEMO_WORDS = ("test", "demo", "example", "sample")
SUFFIXES = {".pem", ".crt", ".cer"}


@dataclass
class AnchorInfo:
    file: str
    subject: str
    sha256: str = ""
    not_before: datetime | None = None
    not_after: datetime | None = None
    is_ca: bool = False
    can_sign_certs: bool = False
    warnings: list[str] = field(default_factory=list)
    problem: bool = False


def _can_sign_certs(cert: x509.Certificate) -> tuple[bool, bool]:
    """Return (is_ca, key_cert_sign), treating unreadable extensions as absent."""
    try:
        is_ca = cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except (x509.ExtensionNotFound, ValueError):
        is_ca = False
    try:
        key_cert_sign = cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign
    except (x509.ExtensionNotFound, ValueError):
        key_cert_sign = False
    return is_ca, key_cert_sign


def describe(cert: x509.Certificate, file: str, now: datetime | None = None) -> AnchorInfo:
    now = now or datetime.now(timezone.utc)
    is_ca, key_cert_sign = _can_sign_certs(cert)
    info = AnchorInfo(
        file=file,
        subject=cert.subject.rfc4514_string() or "(empty subject)",
        sha256=cert.fingerprint(hashes.SHA256()).hex(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        is_ca=is_ca,
        can_sign_certs=is_ca and key_cert_sign,
    )
    if now < info.not_before:
        info.warnings.append("not valid yet")
        info.problem = True
    elif now > info.not_after:
        info.warnings.append("expired")
        info.problem = True
    else:
        days_left = (info.not_after - now).days
        if days_left <= SOON_DAYS:
            info.warnings.append(f"expires in {days_left} days")
    if not info.can_sign_certs:
        info.warnings.append(
            "cannot sign certificates: the verifier only accepts it if a wallet "
            "presents exactly this certificate"
        )
        public_key = cert.public_key()
        if not (
            isinstance(public_key, ec.EllipticCurvePublicKey)
            and isinstance(public_key.curve, ec.SECP256R1)
        ):
            info.warnings.append("its key is not P-256, which the verifier requires")
    name = info.subject.lower()
    if any(word in name for word in DEMO_WORDS):
        info.warnings.append("looks like a demo or test certificate: never use it on a real site")
    return info


def load_folder(folder: Path, now: datetime | None = None) -> list[AnchorInfo]:
    results: list[AnchorInfo] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                certs = x509.load_pem_x509_certificates(path.read_bytes())
        except (ValueError, OSError) as exc:
            results.append(
                AnchorInfo(
                    file=path.name,
                    subject="(unreadable)",
                    warnings=[f"could not be read: {type(exc).__name__}"],
                    problem=True,
                )
            )
            continue
        for cert in certs:
            results.append(describe(cert, path.name, now))
    return results


def _fmt(info: AnchorInfo, now: datetime) -> str:
    lines = [info.file, f"  subject : {info.subject}"]
    if info.not_before and info.not_after:
        left = (info.not_after - now).days
        lines.append(
            f"  valid   : {info.not_before:%Y-%m-%d} to {info.not_after:%Y-%m-%d} ({left} days left)"
        )
        lines.append(f"  sha256  : {info.sha256}")
        lines.append(f"  can sign certificates: {'yes' if info.can_sign_certs else 'no'}")
    for warning in info.warnings:
        lines.append(f"  WARNING : {warning}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    folder = Path(args[0]) if args else Path("verifier-config") / "certs"
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return 1
    now = datetime.now(timezone.utc)
    infos = load_folder(folder, now)
    if not infos:
        print(f"No certificates found in {folder}. The verifier will refuse to start.")
        return 1
    for info in infos:
        print(_fmt(info, now))
        print()
    bad = sum(1 for info in infos if info.problem)
    print(f"{len(infos)} certificate(s), {bad} with a problem.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
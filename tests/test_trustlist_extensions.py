import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID, ObjectIdentifier  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "trustlist.py"
spec = importlib.util.spec_from_file_location("trustlist_ext", SCRIPT)
trustlist = importlib.util.module_from_spec(spec)
sys.modules["trustlist_ext"] = trustlist
spec.loader.exec_module(trustlist)

NOW = dt.datetime.now(dt.timezone.utc)


def make_pem_with_broken_extension(oid):
    """A certificate whose named extension is malformed, so .extensions raises ValueError."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Acme Odd Root")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(7)
        .not_valid_before(NOW - dt.timedelta(days=1))
        .not_valid_after(NOW + dt.timedelta(days=300))
        .add_extension(x509.UnrecognizedExtension(ObjectIdentifier(oid), b"\xff\xff"), critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.mark.parametrize("oid", ["2.5.29.15", "2.5.29.19"])  # keyUsage, basicConstraints
def test_unparseable_extensions_are_reported_as_unreadable_not_as_unable_to_sign(tmp_path, oid):
    (tmp_path / "odd.pem").write_bytes(make_pem_with_broken_extension(oid))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.extensions_unreadable is True
    assert info.problem is False
    text = " ".join(info.warnings)
    assert "could not be parsed" in text
    assert "cannot sign certificates" not in text


def test_report_says_unknown_for_unreadable_extensions(tmp_path, capsys):
    (tmp_path / "odd.pem").write_bytes(make_pem_with_broken_extension("2.5.29.15"))
    assert trustlist.main([str(tmp_path)]) == 0
    assert "unknown (extensions unreadable here)" in capsys.readouterr().out
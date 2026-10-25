import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "trustlist.py"
spec = importlib.util.spec_from_file_location("trustlist", SCRIPT)
trustlist = importlib.util.module_from_spec(spec)
sys.modules["trustlist"] = trustlist  # dataclasses needs the module registered
spec.loader.exec_module(trustlist)

NOW = dt.datetime.now(dt.timezone.utc)


def make_pem(
    cn,
    *,
    ca=True,
    key_cert_sign=True,
    start_days=-10,
    end_days=365,
    curve=None,
):
    curve = curve or ec.SECP256R1()
    key = ec.generate_private_key(curve)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + dt.timedelta(days=start_days))
        .not_valid_after(NOW + dt.timedelta(days=end_days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=not key_cert_sign,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=key_cert_sign,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM)


def write(folder, filename, data):
    path = folder / filename
    path.write_bytes(data)
    return path


def test_good_root_has_no_warnings(tmp_path):
    write(tmp_path, "root.pem", make_pem("Acme Age Root"))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.warnings == []
    assert info.can_sign_certs is True
    assert info.problem is False


def test_expired_certificate_is_a_problem(tmp_path):
    write(tmp_path, "old.pem", make_pem("Acme Old Root", start_days=-400, end_days=-5))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.problem is True
    assert "expired" in info.warnings


def test_not_yet_valid_certificate_is_a_problem(tmp_path):
    write(tmp_path, "future.pem", make_pem("Acme Future Root", start_days=5, end_days=400))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.problem is True
    assert "not valid yet" in info.warnings


def test_expiring_soon_warns_but_is_not_a_problem(tmp_path):
    write(tmp_path, "soon.pem", make_pem("Acme Soon Root", end_days=10))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.problem is False
    assert any(w.startswith("expires in") for w in info.warnings)


def test_signer_certificate_used_directly_is_flagged(tmp_path):
    write(tmp_path, "ds.pem", make_pem("Acme Signer", ca=False, key_cert_sign=False))
    (info,) = trustlist.load_folder(tmp_path)
    assert info.can_sign_certs is False
    assert any("cannot sign certificates" in w for w in info.warnings)
    assert info.problem is False


def test_non_p256_signer_is_flagged(tmp_path):
    pem = make_pem("Acme Big Signer", ca=False, key_cert_sign=False, curve=ec.SECP384R1())
    write(tmp_path, "ds384.pem", pem)
    (info,) = trustlist.load_folder(tmp_path)
    assert any("not P-256" in w for w in info.warnings)


def test_demo_names_are_flagged(tmp_path):
    write(tmp_path, "demo.pem", make_pem("Multipaz TEST IACA"))
    (info,) = trustlist.load_folder(tmp_path)
    assert any("demo or test" in w for w in info.warnings)


def test_unreadable_file_is_a_problem_and_other_files_are_ignored(tmp_path):
    write(tmp_path, "broken.pem", b"this is not a certificate")
    write(tmp_path, "notes.txt", b"ignore me")
    infos = trustlist.load_folder(tmp_path)
    assert len(infos) == 1
    assert infos[0].problem is True
    assert infos[0].subject == "(unreadable)"


def test_main_exit_codes(tmp_path, capsys):
    assert trustlist.main([str(tmp_path)]) == 1  # empty folder
    assert "No certificates found" in capsys.readouterr().out
    write(tmp_path, "root.pem", make_pem("Acme Age Root"))
    assert trustlist.main([str(tmp_path)]) == 0
    write(tmp_path, "old.pem", make_pem("Acme Old Root", start_days=-400, end_days=-5))
    assert trustlist.main([str(tmp_path)]) == 1
    assert trustlist.main([str(tmp_path / "missing")]) == 1


def test_script_never_prints_private_material(tmp_path, capsys):
    write(tmp_path, "root.pem", make_pem("Acme Age Root"))
    trustlist.main([str(tmp_path)])
    assert "PRIVATE" not in capsys.readouterr().out
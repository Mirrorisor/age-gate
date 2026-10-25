import json

from agecheck.reasons import REASONS, explain, reason_from_detail


def test_every_known_reason_has_its_own_sentence():
    sentences = list(REASONS.values())
    assert len(sentences) == len(set(sentences))
    assert all(sentence.strip() for sentence in sentences)


def test_reason_from_json_text_dict_and_bare_code():
    text = '{"reason":"untrusted-issuer","state":"failed"}'
    assert reason_from_detail(text) == "untrusted-issuer"
    assert reason_from_detail(json.loads(text)) == "untrusted-issuer"
    assert reason_from_detail("claim-mismatch") == "claim-mismatch"


def test_reason_from_junk_is_none():
    assert reason_from_detail(None) is None
    assert reason_from_detail(42) is None
    assert reason_from_detail("not json and not a code") is None
    assert reason_from_detail("[1, 2]") is None
    assert reason_from_detail({"reason": 7}) is None


def test_explain_known_unknown_and_missing():
    assert "does not trust" in explain('{"reason":"untrusted-issuer"}')
    assert "over 18" in explain({"reason": "claim-mismatch"})
    assert explain({"reason": "brand-new-code"}) == "Verification failed (brand-new-code)."
    assert explain(None) == "Verification failed."


def test_explain_never_echoes_raw_json():
    message = explain('{"reason":"proof-invalid","state":"failed","detail":"X"}')
    assert "{" not in message and "state" not in message
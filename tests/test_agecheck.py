import pytest
import requests

import agecheck
from agecheck import AgeVerifier, VerifierError, is_verified


class Resp:
    def __init__(self, data, bad_json=False):
        self._data = data
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._data

    def raise_for_status(self):
        pass


def test_is_verified_needs_state_and_age():
    assert is_verified({"state": "verified", "result": {"age_over_18": True}})
    assert not is_verified({"state": "verified", "result": {"age_over_18": False}})
    assert not is_verified({"state": "verified"})
    assert not is_verified({"state": "failed", "reason": "proof-invalid"})
    assert not is_verified({})
    assert not is_verified(None)


def test_start_session_returns_id_and_offer(monkeypatch):
    monkeypatch.setattr(
        agecheck.requests, "post",
        lambda url, **k: Resp({"session_id": "s1", "transports": {"dc": {"o": 1}}}),
    )
    assert AgeVerifier("http://v").start_session() == {"session_id": "s1", "offer": {"o": 1}}


def test_finish_sends_response_and_reports_verdict(monkeypatch):
    seen = {}

    def fake_post(url, **k):
        seen["url"] = url
        seen["json"] = k["json"]
        return Resp({"state": "verified", "result": {"age_over_18": True}})

    monkeypatch.setattr(agecheck.requests, "post", fake_post)
    ok, detail = AgeVerifier("http://v/").finish("s1", "abc")
    assert ok is True
    assert seen["url"] == "http://v/sessions/s1/presentation"
    assert seen["json"] == {"response": "abc"}


def test_unreachable_verifier_raises(monkeypatch):
    def refuse(*a, **k):
        raise requests.ConnectionError("no")

    monkeypatch.setattr(agecheck.requests, "post", refuse)
    with pytest.raises(VerifierError):
        AgeVerifier("http://v").start_session()


def test_garbage_answer_raises(monkeypatch):
    monkeypatch.setattr(agecheck.requests, "post", lambda url, **k: Resp(None, bad_json=True))
    with pytest.raises(VerifierError):
        AgeVerifier("http://v").finish("s1", "abc")

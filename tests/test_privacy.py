import app as site


def test_privacy_page_is_public_and_says_what_is_and_is_not_learned():
    page = site.app.test_client().get("/privacy").get_data(as_text=True)
    assert "zero-knowledge" in page
    assert "not your birthdate" in page
    assert "experimental" in page
    assert "Payment step" not in page  # payment is off by default


def test_privacy_page_mentions_payment_only_when_the_gate_is_on(monkeypatch):
    monkeypatch.setattr(site, "PAYMENT_GATE", True)
    page = site.app.test_client().get("/privacy").get_data(as_text=True)
    assert "Payment step" in page


def test_members_page_links_to_it():
    client = site.app.test_client()
    with client.session_transaction() as s:
        s["is_adult"] = True
    assert 'href="/privacy"' in client.get("/members").get_data(as_text=True)

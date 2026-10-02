"""PII masking with Comprehend (Stubber). No AWS access needed."""

import logging

import boto3
import pytest
from botocore.stub import ANY, Stubber

import core.pii as pii
import core.store as store
from core import config


@pytest.fixture
def comprehend(monkeypatch):
    client = boto3.client("comprehend", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    monkeypatch.setattr(pii, "_client", lambda: client)
    monkeypatch.setenv("CLEARLEGACY_PII_MASKING", "1")
    config.drain_warnings()
    with Stubber(client) as stub:
        yield stub


def _entities(text, *spans):
    return {"Entities": [{"Type": t, "Score": 0.99, "BeginOffset": text.index(s), "EndOffset": text.index(s) + len(s)}
                         for t, s in spans]}


def test_masks_sensitive_values_but_keeps_ids_and_names(comprehend):
    finding = {"findingId": "F1", "clientId": "morgan", "title": "Call Jordan at 555-123-4567",
               "evidence": [{"sourceId": "DEMO-MORGAN-IRA", "value": "SSN 123-45-6789, Taylor Morgan"}]}
    joined = "Call Jordan at 555-123-4567\n\nSSN 123-45-6789, Taylor Morgan"
    comprehend.add_response("detect_pii_entities",
                            _entities(joined, ("PHONE", "555-123-4567"), ("SSN", "123-45-6789"), ("NAME", "Taylor Morgan")),
                            {"Text": joined, "LanguageCode": "en"})
    out = pii.mask_value(finding)
    assert out["title"] == "Call Jordan at [PHONE]"
    assert out["evidence"][0]["value"] == "SSN [SSN], Taylor Morgan"  # names are not masked
    assert out["findingId"] == "F1" and out["evidence"][0]["sourceId"] == "DEMO-MORGAN-IRA"
    assert finding["title"] == "Call Jordan at 555-123-4567"  # original (what the UI shows) untouched


def test_comprehend_failure_uses_local_patterns_with_warning(comprehend):
    comprehend.add_client_error("detect_pii_entities", service_error_code="AccessDeniedException")
    out = pii.mask_texts(["Reach me at jo@example.com or 555-123-4567, SSN 123-45-6789"])[0]
    assert "example.com" not in out and "555-123-4567" not in out and "123-45-6789" not in out
    assert any("local pattern masking" in w for w in config.drain_warnings())


def test_masking_off_makes_no_calls(monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_PII_MASKING", "0")
    monkeypatch.setattr(pii, "_client", lambda: pytest.fail("Comprehend must not be called"))
    assert pii.mask_value({"note": "555-123-4567"}) == {"note": "555-123-4567"}


def test_stored_note_is_masked_in_audit(comprehend, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv("CLEARLEGACY_STORAGE", "json")
    note = "Client called from 555-123-4567"
    comprehend.add_response("detect_pii_entities", _entities(note, ("PHONE", "555-123-4567")), {"Text": note, "LanguageCode": "en"})
    store.log_decision("morgan", "a1", "F1", "confirm", "advisor", note)
    assert store.get_audit("morgan")[0]["note"] == "Client called from [PHONE]"
    assert "555-123-4567" not in (tmp_path / "audit-morgan.json").read_text()


def test_ai_input_is_not_masked(comprehend, monkeypatch):
    # extract_facts receives the original document; masking applies only to stored copies.
    import core.extract as extract
    seen = {}
    monkeypatch.setattr(extract, "call_tool", lambda **kw: seen.update(text=kw["user_text"]) or {"docType": "other", "facts": []})
    extract.extract_facts({"sourceId": "s", "sections": [{"location": "page 1", "text": "SSN 123-45-6789"}]})
    assert "123-45-6789" in seen["text"]
    comprehend.assert_no_pending_responses()


def test_log_messages_are_masked(comprehend, caplog):
    message = "Dropped AI finding: phone 555-123-4567"
    comprehend.add_response("detect_pii_entities", _entities(message, ("PHONE", "555-123-4567")), {"Text": message, "LanguageCode": "en"})
    pii.install_log_masking()
    with caplog.at_level(logging.WARNING, logger="core.explain"):
        logging.getLogger("core.explain").warning("Dropped AI finding: phone %s", "555-123-4567")
    assert "555-123-4567" not in caplog.text and "[PHONE]" in caplog.text

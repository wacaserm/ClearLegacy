"""Textract OCR in the document reader, with botocore Stubber. No AWS access needed."""

from pathlib import Path

import boto3
import pytest
from botocore.stub import ANY, Stubber

import core.ocr as ocr
from core import config
from core.document_reader import read_document
from core.validation import validate_facts

SCANNED = Path(__file__).parent / "fixtures" / "scanned"
ONE_PAGE = (SCANNED / "morgan_planning_summary_scanned.pdf").read_bytes()
TWO_PAGE = (SCANNED / "johnson_will_scanned_2page.pdf").read_bytes()
LINE = "I want Casey Morgan to receive 100% as primary beneficiary of my IRA DEMO-MORGAN-IRA."


def _line(text, page=1):
    return {"BlockType": "LINE", "Text": text, "Page": page}


@pytest.fixture
def clients(monkeypatch):
    textract = boto3.client("textract", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    monkeypatch.setattr(ocr, "_client", lambda service: {"textract": textract, "s3": s3}[service])
    monkeypatch.setattr(ocr, "POLL_SECONDS", 0)
    monkeypatch.setenv("CLEARLEGACY_USE_TEXTRACT", "1")
    monkeypatch.setenv("CLEARLEGACY_BUCKET", "test-bucket")
    config.drain_warnings()
    with Stubber(textract) as t, Stubber(s3) as s:
        yield t, s


def test_single_page_scan_is_ocrd_and_quotes_validate(clients):
    textract, _ = clients
    textract.add_response("detect_document_text", {"Blocks": [_line("Client Planning Summary"), _line(LINE)]},
                          {"Document": {"Bytes": ONE_PAGE}})
    doc = read_document(ONE_PAGE, "planning_summary.pdf")
    assert doc["status"] == "ok"
    assert doc["sections"] == [{"location": "page 1", "text": f"Client Planning Summary\n{LINE}"}]
    assert doc["ocrPages"] == [1] and doc["warnings"] == []
    facts = {"sourceId": doc["sourceId"], "facts": [{"field": "intended_beneficiary", "value": "Casey Morgan",
             "location": "page 1", "quote": LINE}], "warnings": []}
    assert validate_facts(facts, doc)["facts"]  # Role 1's quote check works on OCR text


def test_multi_page_scan_uses_s3_async_and_deletes_temp_file(clients):
    textract, s3 = clients
    s3.add_response("put_object", {"VersionId": "v1"},
                    {"Bucket": "test-bucket", "Key": ANY, "Body": TWO_PAGE, "ServerSideEncryption": "AES256"})
    textract.add_response("start_document_text_detection", {"JobId": "job-1"}, {"DocumentLocation": ANY})
    textract.add_response("get_document_text_detection", {"JobStatus": "IN_PROGRESS"}, {"JobId": "job-1"})
    textract.add_response("get_document_text_detection",
                          {"JobStatus": "SUCCEEDED", "Blocks": [_line("Page one text", 1)], "NextToken": "t"},
                          {"JobId": "job-1"})
    textract.add_response("get_document_text_detection",
                          {"JobStatus": "SUCCEEDED", "Blocks": [_line("Page two text", 2)]},
                          {"JobId": "job-1", "NextToken": "t"})
    s3.add_response("delete_object", {}, {"Bucket": "test-bucket", "Key": ANY, "VersionId": "v1"})
    doc = read_document(TWO_PAGE, "will.pdf")
    assert [s["text"] for s in doc["sections"]] == ["Page one text", "Page two text"]
    assert doc["status"] == "ok" and doc["ocrPages"] == [1, 2] and doc["warnings"] == []
    s3.assert_no_pending_responses()


def test_failed_job_falls_back_with_warning(clients):
    textract, s3 = clients
    s3.add_response("put_object", {"VersionId": "v1"}, {"Bucket": "test-bucket", "Key": ANY, "Body": TWO_PAGE,
                                                         "ServerSideEncryption": "AES256"})
    textract.add_response("start_document_text_detection", {"JobId": "j"}, {"DocumentLocation": ANY})
    textract.add_response("get_document_text_detection", {"JobStatus": "FAILED", "StatusMessage": "bad"}, {"JobId": "j"})
    s3.add_response("delete_object", {}, {"Bucket": "test-bucket", "Key": ANY, "VersionId": "v1"})
    doc = read_document(TWO_PAGE, "will.pdf")
    assert doc["status"] == "needs_ocr" and all(not s["text"] for s in doc["sections"])
    assert any("OCR unavailable" in w for w in doc["warnings"])
    assert any("OCR unavailable" in w for w in config.drain_warnings())


def test_timeout_falls_back(clients, monkeypatch):
    textract, s3 = clients
    monkeypatch.setattr(ocr, "TIMEOUT_SECONDS", -1)
    s3.add_response("put_object", {"VersionId": "v1"}, {"Bucket": "test-bucket", "Key": ANY, "Body": TWO_PAGE,
                                                         "ServerSideEncryption": "AES256"})
    textract.add_response("start_document_text_detection", {"JobId": "j"}, {"DocumentLocation": ANY})
    textract.add_response("get_document_text_detection", {"JobStatus": "IN_PROGRESS"}, {"JobId": "j"})
    s3.add_response("delete_object", {}, {"Bucket": "test-bucket", "Key": ANY, "VersionId": "v1"})
    doc = read_document(TWO_PAGE, "will.pdf")
    assert doc["status"] == "needs_ocr" and any("did not finish" in w for w in doc["warnings"])


def test_access_denied_falls_back(clients):
    textract, _ = clients
    textract.add_client_error("detect_document_text", service_error_code="AccessDeniedException")
    doc = read_document(ONE_PAGE, "planning_summary.pdf")
    assert doc["status"] == "needs_ocr" and any("OCR unavailable" in w for w in doc["warnings"])


def test_textract_off_keeps_old_behavior(monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_USE_TEXTRACT", "0")
    monkeypatch.setattr(ocr, "_client", lambda service: pytest.fail("Textract must not be called"))
    doc = read_document(ONE_PAGE, "planning_summary.pdf")
    assert doc["status"] == "needs_ocr" and doc["sections"][0]["text"] == ""


def test_text_pdfs_never_call_textract(monkeypatch):
    monkeypatch.setattr(ocr, "_client", lambda service: pytest.fail("Textract must not be called"))
    sample = Path(__file__).parent.parent / "sample_data" / "01_morgan_discrepancies" / "planning_summary.pdf"
    assert read_document(sample.read_bytes(), sample.name)["status"] == "ok"


def test_image_upload_is_ocrd(clients):
    textract, _ = clients
    textract.add_response("detect_document_text", {"Blocks": [_line(LINE)]}, {"Document": {"Bytes": b"\x89PNG"}})
    doc = read_document(b"\x89PNG", "scan.png")
    assert doc["status"] == "ok" and doc["sections"][0]["text"] == LINE

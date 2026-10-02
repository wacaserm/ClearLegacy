"""S3 copy of uploads in the pipeline, with botocore Stubber. No AWS access needed."""

from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

import core.pipeline as pipeline
import core.s3_documents as s3_documents
from core import config

PDF = (Path(__file__).parent.parent / "sample_data" / "01_morgan_discrepancies" / "planning_summary.pdf").read_bytes()


@pytest.fixture
def s3(monkeypatch):
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    monkeypatch.setattr(s3_documents, "_client", lambda: client)
    monkeypatch.setenv("CLEARLEGACY_BUCKET", "test-bucket")
    config.drain_warnings()
    with Stubber(client) as stub:
        yield stub


def test_upload_stored_encrypted_and_key_recorded(s3, monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_USE_S3", "1")
    s3.add_response("put_object", {"VersionId": "v9"}, {"Bucket": "test-bucket", "Key": "clients/morgan/planning_summary.pdf",
                                                         "Body": PDF, "ServerSideEncryption": "AES256"})
    doc = pipeline._document_input((PDF, "planning_summary.pdf"), "morgan")
    assert doc["s3Key"] == "clients/morgan/planning_summary.pdf" and doc["s3VersionId"] == "v9"
    assert doc["sections"][0]["text"]  # local reading unchanged


def test_s3_failure_falls_back_with_warning(s3, monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_USE_S3", "1")
    s3.add_client_error("put_object", service_error_code="AccessDenied")
    doc = pipeline._document_input((PDF, "planning_summary.pdf"), "morgan")
    assert "s3Key" not in doc and doc["sections"][0]["text"]
    assert any("S3 storage unavailable" in w for w in config.drain_warnings())


def test_s3_off_by_default(monkeypatch):
    monkeypatch.delenv("CLEARLEGACY_USE_S3", raising=False)
    monkeypatch.setattr(s3_documents, "_client", lambda: pytest.fail("S3 must not be called"))
    assert "s3Key" not in pipeline._document_input((PDF, "planning_summary.pdf"), "morgan")

"""Amazon Textract OCR for pages with no text layer.

Single-page PDFs and images use synchronous DetectDocumentText with Bytes.
Multi-page scanned PDFs are uploaded to the ClearLegacy bucket (SSE-S3) and
read with asynchronous StartDocumentTextDetection, then the temporary object
version is deleted. Errors raise OcrError so callers can fall back.
"""

import hashlib
import time
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from core import config
from core.bedrock_client import get_client

POLL_SECONDS = 2
TIMEOUT_SECONDS = 60

# Streamlit previews uploads on every rerun; cache by file content so each
# unique file is sent to Textract once per process.
_cache: dict[str, object] = {}


def _key(kind: str, data: bytes) -> str:
    return f"{kind}:{hashlib.sha256(data).hexdigest()}"


class OcrError(RuntimeError):
    """OCR could not run; the caller keeps the page empty and warns."""


def _client(service: str):
    return get_client(service)


def _lines(blocks) -> dict[int, list[str]]:
    pages: dict[int, list[str]] = {}
    for block in blocks:
        if block.get("BlockType") == "LINE":
            pages.setdefault(block.get("Page", 1), []).append(block.get("Text", ""))
    return pages


def ocr_single(data: bytes) -> str:
    """OCR one image or single-page PDF; returns its text."""
    key = _key("single", data)
    if key not in _cache:
        _cache[key] = _ocr_single(data)
    return _cache[key]


def _ocr_single(data: bytes) -> str:
    try:
        response = _client("textract").detect_document_text(Document={"Bytes": data})
    except (ClientError, BotoCoreError) as error:
        raise OcrError(f"Textract could not read the page: {error}") from error
    return "\n".join(_lines(response.get("Blocks", [])).get(1, []))


def ocr_multipage(data: bytes, filename: str) -> dict[int, str]:
    """OCR a multi-page PDF through S3 and the async API; returns {page: text}."""
    key = _key("multi", data)
    if key not in _cache:
        _cache[key] = _ocr_multipage(data, filename)
    return _cache[key]


def _ocr_multipage(data: bytes, filename: str) -> dict[int, str]:
    bucket = config.bucket()
    if not bucket:
        raise OcrError("multi-page OCR needs CLEARLEGACY_BUCKET (run infra/setup_aws.py)")
    s3 = _client("s3")
    textract = _client("textract")
    key = f"ocr/{uuid.uuid4()}/{filename}"
    try:
        put = s3.put_object(Bucket=bucket, Key=key, Body=data, ServerSideEncryption="AES256")
        job = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
        )["JobId"]
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while True:
            response = textract.get_document_text_detection(JobId=job)
            status = response["JobStatus"]
            if status == "SUCCEEDED":
                break
            if status == "FAILED":
                raise OcrError(f"Textract job failed: {response.get('StatusMessage', 'no reason given')}")
            if time.monotonic() > deadline:
                raise OcrError(f"Textract did not finish within {TIMEOUT_SECONDS}s")
            time.sleep(POLL_SECONDS)
        blocks = list(response.get("Blocks", []))
        while response.get("NextToken"):
            response = textract.get_document_text_detection(JobId=job, NextToken=response["NextToken"])
            blocks.extend(response.get("Blocks", []))
    except (ClientError, BotoCoreError) as error:
        raise OcrError(f"Textract could not read the document: {error}") from error
    finally:
        _delete_quietly(s3, bucket, key, locals().get("put"))
    return {page: "\n".join(lines) for page, lines in _lines(blocks).items()}


def _delete_quietly(s3, bucket: str, key: str, put_response) -> None:
    """Remove the temporary upload, including its version (the bucket is versioned)."""
    try:
        version = (put_response or {}).get("VersionId")
        if version:
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version)
        else:
            s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        config.aws_warning(f"Temporary OCR file s3://{bucket}/{key} could not be deleted.")

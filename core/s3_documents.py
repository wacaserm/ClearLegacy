"""Optional S3 copy of uploaded documents (CLEARLEGACY_USE_S3=1).

Files go to s3://<bucket>/clients/<clientId>/<filename> with SSE-S3 encryption.
The bucket is versioned, so re-uploading a filename keeps the earlier version.
Local processing never depends on this succeeding.
"""

from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from core import config
from core.bedrock_client import get_client


class S3StorageError(RuntimeError):
    pass


def _client():
    return get_client("s3")


def store_upload(client_id: str, filename: str, data: bytes) -> dict:
    """Upload one document; returns {"s3Bucket", "s3Key", "s3VersionId"}."""
    bucket = config.bucket()
    if not bucket:
        raise S3StorageError("CLEARLEGACY_BUCKET is not set (run infra/setup_aws.py)")
    key = f"clients/{client_id}/{Path(filename).name}"
    try:
        response = _client().put_object(Bucket=bucket, Key=key, Body=data, ServerSideEncryption="AES256")
    except (ClientError, BotoCoreError) as error:
        raise S3StorageError(f"could not store {Path(filename).name} in S3: {error}") from error
    return {"s3Bucket": bucket, "s3Key": key, "s3VersionId": response.get("VersionId")}

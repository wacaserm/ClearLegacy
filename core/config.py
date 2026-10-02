"""Feature flags for optional AWS services, and a collector for fallback warnings.

Defaults keep the local behavior: JSON storage, no S3, Textract only for pages
with no text layer, no PII masking. Every AWS path falls back to local behavior
on error and records a warning here instead of crashing.
"""

import os
import threading

REGION = (
    os.environ.get("BEDROCK_REGION")
    or os.environ.get("AWS_REGION")
    or os.environ.get("AWS_DEFAULT_REGION")
    or "us-east-1"
)


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def storage() -> str:
    """'json' (default) or 'dynamodb'."""
    value = os.environ.get("CLEARLEGACY_STORAGE", "json").strip().lower()
    return value if value in {"json", "dynamodb"} else "json"


def use_s3() -> bool:
    return _flag("CLEARLEGACY_USE_S3", "0")


def use_textract() -> bool:
    return _flag("CLEARLEGACY_USE_TEXTRACT", "1")


def pii_masking() -> bool:
    return _flag("CLEARLEGACY_PII_MASKING", "0")


def bucket() -> str | None:
    return os.environ.get("CLEARLEGACY_BUCKET", "").strip() or None


def table_prefix() -> str:
    return os.environ.get("CLEARLEGACY_TABLE_PREFIX", "clearlegacy-").strip() or "clearlegacy-"


def table_name(kind: str) -> str:
    return f"{table_prefix()}{kind}"


def summary() -> dict:
    """Active settings, for the app header and scripts/check_setup.py."""
    return {
        "storage": storage(),
        "s3": use_s3(),
        "textract": use_textract(),
        "piiMasking": pii_masking(),
        "bucket": bucket(),
        "tablePrefix": table_prefix(),
        "region": REGION,
    }


# --------------------------------------------------------------------------- fallback warnings

_warnings: list[str] = []
_lock = threading.Lock()


def aws_warning(message: str) -> None:
    """Record a fallback warning once, so the app can show it."""
    with _lock:
        if message not in _warnings:
            _warnings.append(message)


def drain_warnings() -> list[str]:
    """Return and clear recorded warnings."""
    with _lock:
        out = list(_warnings)
        _warnings.clear()
        return out

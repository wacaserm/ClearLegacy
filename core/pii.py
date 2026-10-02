"""PII masking for stored and logged data (CLEARLEGACY_PII_MASKING=1), using Amazon Comprehend.

Masks SSNs, bank account/routing and card numbers, phone numbers and emails in
what is written to logs, the audit trail, runtime JSON files and DynamoDB.
It is NOT applied to text sent to the AI for extraction (names are needed for
matching) or to what the advisor sees in the UI. Identifier fields
(clientId, findingId, accountId, ...) are never masked, so records stay linked.

If Comprehend fails while masking is on, a local pattern-based mask is used
instead (never unmasked writes) and a warning is recorded.
"""

import logging
import re

from botocore.exceptions import BotoCoreError, ClientError

from core import config
from core.bedrock_client import get_client

MASK_TYPES = {"SSN", "BANK_ACCOUNT_NUMBER", "BANK_ROUTING", "CREDIT_DEBIT_NUMBER", "PHONE", "EMAIL"}
MIN_SCORE = 0.5
SKIP_KEYS = {
    "clientId", "analysisId", "findingId", "accountId", "auditId", "sourceId", "sourceType",
    "priority", "field", "location", "timestamp", "decision", "status", "s3Key", "s3Bucket", "s3VersionId",
}
_SEPARATOR = "\n\n"
_MAX_CHARS = 90_000  # DetectPiiEntities accepts up to 100 KB of UTF-8 per call

# Local fallback patterns, only used when Comprehend is unavailable.
_PATTERNS = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")),
    ("BANK_ACCOUNT_NUMBER", re.compile(r"\b\d{8,17}\b")),
]


def _client():
    return get_client("comprehend")


def _comprehend_mask(text: str) -> str:
    entities = _client().detect_pii_entities(Text=text, LanguageCode="en")["Entities"]
    for entity in sorted(entities, key=lambda e: e["BeginOffset"], reverse=True):
        if entity["Type"] in MASK_TYPES and entity.get("Score", 1) >= MIN_SCORE:
            text = text[: entity["BeginOffset"]] + f"[{entity['Type']}]" + text[entity["EndOffset"]:]
    return text


def _pattern_mask(text: str) -> str:
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


def mask_texts(texts: list[str]) -> list[str]:
    """Mask a batch of strings, using one Comprehend call per ~90k characters."""
    if not config.pii_masking() or not texts:
        return list(texts)
    out: list[str] = []
    batch: list[str] = []

    def flush():
        if not batch:
            return
        joined = _SEPARATOR.join(batch)
        try:
            masked = _comprehend_mask(joined).split(_SEPARATOR)
            if len(masked) != len(batch):  # a mask spanned a separator; mask individually
                masked = [_comprehend_mask(t) for t in batch]
        except (ClientError, BotoCoreError) as error:
            config.aws_warning(f"Comprehend unavailable; used local pattern masking instead ({error}).")
            masked = [_pattern_mask(t) for t in batch]
        out.extend(masked)
        batch.clear()

    size = 0
    for text in texts:
        if size + len(text) > _MAX_CHARS:
            flush()
            size = 0
        batch.append(text)
        size += len(text) + len(_SEPARATOR)
    flush()
    return out


def mask_value(value):
    """Return a copy of a dict/list/str with string values masked (identifier keys kept)."""
    if not config.pii_masking():
        return value
    slots: list[tuple] = []

    def collect(node, parent, key):
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in SKIP_KEYS:
                    collect(v, node, k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                collect(v, node, i)
        elif isinstance(node, str) and node.strip() and parent is not None:
            slots.append((parent, key, node))

    import copy

    copied = copy.deepcopy(value)
    if isinstance(copied, str):
        return mask_texts([copied])[0]
    collect(copied, None, None)
    for (parent, key, _), masked in zip(slots, mask_texts([s[2] for s in slots])):
        parent[key] = masked
    return copied


class MaskingFilter(logging.Filter):
    """Masks ClearLegacy log messages when CLEARLEGACY_PII_MASKING=1."""

    def filter(self, record: logging.LogRecord) -> bool:
        if config.pii_masking():
            try:
                record.msg = mask_texts([record.getMessage()])[0]
                record.args = None
            except Exception:
                record.msg, record.args = "[log message withheld: PII masking failed]", None
        return True


_LOGGERS = ("core.explain", "core.extract", "core.assistant", "core.validation", "core.pipeline", "core.store")


def install_log_masking() -> None:
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, MaskingFilter) for f in logger.filters):
            logger.addFilter(MaskingFilter())

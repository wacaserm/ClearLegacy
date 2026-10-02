"""Document intelligence: extract quoted, located facts from a document with Bedrock.

Owner: Role 1. Input is the shared document shape from core/document_reader.py
(Role 3). The model only records what the document states; every fact carries a
location and verbatim quote, and core/validation.validate_facts() excludes any
fact whose quote is not found. Comparison against accounts happens in core/rules.py.
"""

import logging
import re
from pathlib import Path

from botocore.exceptions import ClientError, NoCredentialsError
from pypdf import PdfReader

from core.bedrock_client import (
    MODEL_ID,
    AWSCredentialsExpired,
    call_tool,
    get_client,
    is_credentials_error,
)
from core.validation import validate_facts

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

DOC_TYPES = [
    "will", "trust", "poa", "planning_summary", "account_records", "beneficiary_form", "other",
]

# Extraction field vocabulary agreed with Role 2 (rules) — see README and prompts/extraction.txt.
FACT_FIELDS = [
    "document_id", "document_date", "snapshot_date", "governing_state", "client_name",
    "family_member", "intended_beneficiary", "intentional_exclusion", "residuary_beneficiary",
    "executor", "alternate_executor", "trustee", "successor_trustee",
    "poa_agent", "successor_poa_agent", "guardian",
    "trust_owned_account", "account_beneficiary", "account_registration", "account_owner",
    "missing_information", "unspecified_intention",
]


# --------------------------------------------------------------------------- reading
# Stand-in readers for local runs and tests. The app pipeline should use
# core/document_reader.read_document (Role 3), which returns the same shape.

_PAGE_MARKER = re.compile(r"^=== PAGE (\d+) ===[ \t]*$", re.MULTILINE)


def read_txt(path) -> list[dict]:
    """Read a .txt document whose pages are separated by lines like '=== PAGE 2 ==='."""
    text = Path(path).read_text(encoding="utf-8")
    parts = _PAGE_MARKER.split(text)
    if len(parts) == 1:
        return [{"page": 1, "text": text.strip()}]
    return [
        {"page": int(parts[i]), "text": parts[i + 1].strip()}
        for i in range(1, len(parts), 2)
    ]


def _textract_single_page(data: bytes) -> str:
    try:
        resp = get_client("textract").detect_document_text(Document={"Bytes": data})
    except (ClientError, NoCredentialsError) as exc:
        if is_credentials_error(exc):
            raise AWSCredentialsExpired() from exc
        raise
    return "\n".join(b["Text"] for b in resp.get("Blocks", []) if b["BlockType"] == "LINE")


def read_pdf(path) -> list[dict]:
    """Return [{"page": int, "text": str}] for a PDF or page-marked .txt file.

    A scanned single-page PDF is OCR'd with Textract; scanned pages in longer
    PDFs are left "" with a warning (multi-page OCR is future work).
    """
    path = Path(path)
    if path.suffix.lower() == ".txt":
        return read_txt(path)
    reader = PdfReader(str(path))
    pages = [
        {"page": i, "text": (page.extract_text() or "").strip()}
        for i, page in enumerate(reader.pages, start=1)
    ]
    empty = [p["page"] for p in pages if not p["text"]]
    if empty and len(pages) == 1:
        log.info("%s has no text layer; running Textract OCR", path.name)
        pages[0]["text"] = _textract_single_page(path.read_bytes()).strip()
    elif empty:
        log.warning("%s: pages %s have no extractable text; left empty", path.name, empty)
    return pages


def load_document(path, doc_type: str | None = None, source_id: str | None = None) -> dict:
    """Build the shared document shape from a local .pdf or .txt file."""
    path = Path(path)
    return {
        "sourceId": source_id or re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-"),
        "filename": path.name,
        "docType": doc_type,
        "sections": [{"location": f"page {p['page']}", "text": p["text"]} for p in read_pdf(path)],
    }


# --------------------------------------------------------------------------- extraction

_NULLABLE = {"type": ["string", "null"]}

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "docType": {"type": "string", "enum": DOC_TYPES},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": FACT_FIELDS},
                    "value": {"type": "string", "description": "Name, date (YYYY-MM-DD), state code, or short statement."},
                    "location": {"type": "string", "description": "Copied exactly from the section marker, e.g. 'page 1'."},
                    "quote": {"type": "string", "description": "Verbatim supporting text from that section, under 40 words."},
                    "accountRef": {**_NULLABLE, "description": "Account reference as written, e.g. 'DEMO-MORGAN-IRA'."},
                    "tier": {"type": ["string", "null"], "enum": ["primary", "contingent", None]},
                    "allocation": {**_NULLABLE, "description": "e.g. '100%', '50%', 'equal shares'."},
                    "relationship": {**_NULLABLE, "description": "As stated, e.g. 'daughter', 'former spouse'."},
                    "asOf": {**_NULLABLE, "description": "Date the fact was recorded or updated, YYYY-MM-DD, if stated."},
                },
                "required": [
                    "field", "value", "location", "quote",
                    "accountRef", "tier", "allocation", "relationship", "asOf",
                ],
            },
        },
    },
    "required": ["docType", "facts"],
}

EXTRACTION_PROMPT = (PROMPTS / "extraction.txt").read_text(encoding="utf-8")


def _format_sections(sections: list[dict]) -> str:
    return "\n\n".join(f"[location: {s['location']}]\n{s['text']}" for s in sections)


def extract_facts(document: dict) -> dict:
    """Return {sourceId, docType, facts: [...], warnings: [...]} for a document.

    Facts are not yet quote-validated; run core.validation.validate_facts next.
    """
    source_id = document.get("sourceId") or document.get("filename") or "document"
    sections = [s for s in document.get("sections", []) if (s.get("text") or "").strip()]
    if not sections:
        return {
            "sourceId": source_id,
            "docType": document.get("docType") or "other",
            "facts": [],
            "warnings": [
                f"No readable text in {document.get('filename') or source_id}. "
                "Upload a selectable-text file or run OCR."
            ],
        }

    label = document.get("docType") or "not specified"
    user_text = (
        f"Uploader's document type label: {label}\n\n"
        f"<document>\n{_format_sections(sections)}\n</document>\n\n"
        "Record the facts using the record_document_facts tool."
    )
    result = call_tool(
        system=EXTRACTION_PROMPT,
        user_text=user_text,
        tool_name="record_document_facts",
        tool_description="Record facts stated in a document, each with its location and verbatim quote.",
        schema=FACTS_SCHEMA,
        model_id=MODEL_ID,
        max_tokens=8192,
    )
    doc_type = document.get("docType") or result.get("docType")
    raw_facts = result.get("facts")
    facts, warnings = [], []
    for raw in raw_facts if isinstance(raw_facts, list) else []:
        fact, problem = _clean_fact(raw)
        if fact is None:
            warnings.append(f"Skipped malformed fact from {source_id}: {problem}")
            log.warning("Skipped malformed fact from %s: %s", source_id, problem)
        else:
            facts.append(fact)
    if not isinstance(raw_facts, list):
        warnings.append(f"Model returned no fact list for {source_id}")
    return {
        "sourceId": source_id,
        "docType": doc_type if doc_type in DOC_TYPES else "other",
        "facts": facts,
        "warnings": warnings,
    }


_OPTIONAL_KEYS = ("accountRef", "tier", "allocation", "relationship", "asOf")


def _clean_fact(raw) -> tuple[dict | None, str | None]:
    """Coerce one model fact into the contract shape, or explain why it can't be used."""
    if not isinstance(raw, dict):
        return None, "not an object"
    if raw.get("field") not in FACT_FIELDS:
        return None, f"unknown field {raw.get('field')!r}"
    fact = {}
    for key in ("field", "value", "location", "quote"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, f"{raw.get('field')} is missing {key}"
        fact[key] = value.strip()
    for key in _OPTIONAL_KEYS:
        value = raw.get(key)
        fact[key] = value.strip() if isinstance(value, str) and value.strip() else None
    if fact["tier"] not in (None, "primary", "contingent"):
        fact["tier"] = None
    return fact, None


def extract_document(path, doc_type: str | None = None, source_id: str | None = None) -> dict:
    """Convenience for local runs: load, extract, and validate one file."""
    document = load_document(path, doc_type, source_id)
    return validate_facts(extract_facts(document), document)

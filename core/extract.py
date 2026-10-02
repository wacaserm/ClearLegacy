"""Document intelligence: read estate documents and extract verifiable facts.

The model only extracts what a document states. Every fact carries a page number
and a verbatim quote, and validate_facts() drops anything whose quote cannot be
found in the source text. Comparing facts against accounts is done by plain
Python rules in core/rules.py, not here.
"""

import copy
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

log = logging.getLogger(__name__)

DOC_TYPES = ["will", "trust", "poa", "beneficiary_form", "other"]
ROLES = ["beneficiary", "executor", "trustee", "successor_trustee", "poa_agent", "guardian", "other"]

_PAGE_MARKER = re.compile(r"^=== PAGE (\d+) ===[ \t]*$", re.MULTILINE)


# --------------------------------------------------------------------------- reading


def read_txt(path) -> list[dict]:
    """Read a .txt document whose pages are separated by lines like '=== PAGE 2 ==='."""
    text = Path(path).read_text(encoding="utf-8")
    parts = _PAGE_MARKER.split(text)
    if len(parts) == 1:
        return [{"page": 1, "text": text.strip()}]
    # parts = [preamble, "1", page1_text, "2", page2_text, ...]
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
    """Return [{"page": 1-based int, "text": str}] for a PDF or page-marked .txt file.

    Scanned pages with no text layer are OCR'd with Textract only when the PDF
    has a single page; otherwise their text is "" and a warning is logged.
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
        log.warning(
            "%s: pages %s have no extractable text (scanned?). Multi-page OCR "
            "is not supported yet; those pages are left empty.",
            path.name,
            empty,
        )
    return pages


# --------------------------------------------------------------------------- extraction

_SOURCED = {"page": {"type": ["integer", "null"]}, "quote": {"type": ["string", "null"]}}

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "docType": {"type": "string", "enum": DOC_TYPES},
        "dateSigned": {
            "type": "object",
            "description": "Date the document was signed/executed. All fields null if absent.",
            "properties": {
                "value": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"},
                **_SOURCED,
            },
            "required": ["value", "page", "quote"],
        },
        "governingState": {
            "type": "object",
            "description": "State whose law governs the document. All fields null if absent.",
            "properties": {
                "value": {"type": ["string", "null"], "description": "Two-letter US state code or null"},
                **_SOURCED,
            },
            "required": ["value", "page", "quote"],
        },
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "relationship": {"type": "string", "description": "As stated, e.g. 'daughter'; '' if not stated"},
                    "role": {"type": "string", "enum": ROLES},
                    "share": {"type": ["string", "null"], "description": "e.g. 'equal third' or '100%'; null if not stated"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["name", "relationship", "role", "share", "page", "quote"],
            },
        },
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "disposition": {"type": "string", "description": "What the document says happens to it"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["description", "disposition", "page", "quote"],
            },
        },
    },
    "required": ["docType", "dateSigned", "governingState", "people", "assets"],
}

EXTRACT_SYSTEM = """You extract facts from estate planning documents (wills, trusts, powers of attorney, beneficiary forms) for a financial advisor's review tool.

Rules:
- Extract only what the document explicitly states. Never infer, assume, or fill gaps from general knowledge.
- Every fact must cite the page number shown in the [PAGE N] marker where it appears, and a short verbatim quote from that page (under 40 words) that supports it. Copy the quote character-for-character; do not paraphrase, abbreviate, or use ellipses.
- Use null when a value is absent. If the signing date or governing state is not stated, set value, page and quote all to null.
- List each person once per role. A person named both as beneficiary and executor gets two entries.
- Assets: include only specific assets or accounts the document mentions by description, with what the document says happens to them.
- You are not giving legal advice or judging validity. Just record what the text says."""


def _format_pages(pages: list[dict]) -> str:
    return "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)


def extract_facts(pages: list[dict], doc_type: str) -> dict:
    """Ask the main model for structured, quoted facts from the document pages."""
    user_text = (
        f"The uploader labeled this document as: {doc_type}\n\n"
        f"<document>\n{_format_pages(pages)}\n</document>\n\n"
        "Record the facts using the record_document_facts tool."
    )
    return call_tool(
        system=EXTRACT_SYSTEM,
        user_text=user_text,
        tool_name="record_document_facts",
        tool_description="Record facts stated in an estate document, each with its page and verbatim quote.",
        schema=FACTS_SCHEMA,
        model_id=MODEL_ID,
        max_tokens=4096,
    )


# --------------------------------------------------------------------------- validation

_QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _normalize(text: str) -> str:
    text = text.translate(_QUOTE_CHARS).lower()
    return re.sub(r"\s+", " ", text).strip()


_ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")


def _fragments(quote: str) -> list[str]:
    """Split a quote on ellipses; every fragment must be verbatim document text."""
    parts = [_normalize(p).strip(" \"'") for p in _ELLIPSIS.split(_normalize(quote))]
    return [p for p in parts if p]


def _contains_in_order(text: str, fragments: list[str]) -> bool:
    pos = 0
    for frag in fragments:
        pos = text.find(frag, pos)
        if pos < 0:
            return False
        pos += len(frag)
    return True


def _locate(quote: str, claimed_page, pages: list[dict]):
    """Return the page number containing the quote, preferring the claimed page; None if absent.

    A quote shortened with "..." matches only if every fragment appears, in order, on one page.
    """
    fragments = _fragments(quote)
    if not fragments:
        return None
    by_page = {p["page"]: _normalize(p["text"]) for p in pages}
    if claimed_page in by_page and _contains_in_order(by_page[claimed_page], fragments):
        return claimed_page
    for page_num, text in by_page.items():
        if _contains_in_order(text, fragments):
            return page_num
    return None


def validate_facts(facts: dict, pages: list[dict]) -> dict:
    """Keep only facts whose quote appears in the page text; fix wrong page numbers.

    Returns a copy of facts with a "dropped" list of {"field", "item", "reason"}.
    Dropped scalar fields (dateSigned, governingState) are reset to all-null.
    """
    out = copy.deepcopy(facts)
    dropped = list(out.get("dropped", []))

    def check(field: str, item: dict) -> bool:
        found = _locate(item.get("quote") or "", item.get("page"), pages)
        if found is None:
            dropped.append({"field": field, "item": item, "reason": "quote not found in document"})
            log.warning("Dropped %s (quote not found): %r", field, item.get("quote"))
            return False
        if found != item.get("page"):
            log.info("Corrected %s page %s -> %s", field, item.get("page"), found)
            item["page"] = found
        return True

    for field in ("dateSigned", "governingState"):
        item = out.get(field)
        if not item or (item.get("value") is None and not item.get("quote")):
            out[field] = {"value": None, "page": None, "quote": None}
        elif not check(field, item):
            out[field] = {"value": None, "page": None, "quote": None}

    for field in ("people", "assets"):
        out[field] = [item for item in out.get(field, []) if check(field, item)]

    out["dropped"] = dropped
    return out


def extract_document(path, doc_type: str) -> dict:
    """Read a document, extract facts with the model, and validate every quote."""
    path = Path(path)
    pages = read_pdf(path)
    if not any(p["text"] for p in pages):
        raise ValueError(f"{path.name}: no readable text found")
    facts = validate_facts(extract_facts(pages, doc_type), pages)
    facts["source"] = path.name
    return facts

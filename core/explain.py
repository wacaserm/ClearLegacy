"""Plain-English explanations of findings, plus an optional AI pass for conflicts rules may miss.

The AI never decides what the law is. explain() rewrites a rules finding for an
advisor; find_additional_conflicts() only surfaces candidates for human review,
and every one must cite evidence that verifies against already-validated facts.
"""

import json
import logging

from core.bedrock_client import FAST_MODEL_ID, MODEL_ID, call_tool
from core.extract import _locate, _normalize

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- explain

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "At most 2 plain-English sentences describing the issue and why it matters.",
        },
        "recommendedAction": {
            "type": "string",
            "description": "One sentence: review with the client and their attorney.",
        },
    },
    "required": ["explanation", "recommendedAction"],
}

EXPLAIN_SYSTEM = """You help financial advisors understand flagged inconsistencies between a client's estate documents and account records.

Write for an advisor with no legal training:
- explanation: at most 2 short, plain-English sentences. Say what does not match and the practical consequence, using only the evidence provided. No legal jargon, no citations of law.
- recommendedAction: exactly one sentence recommending the advisor review the issue with the client and the client's attorney.

Never give legal advice, never state a definitive legal conclusion, and never tell the client to change, sign, or revoke legal documents themselves. Do not invent facts beyond the evidence."""


def explain(finding: dict) -> dict:
    """Return {"explanation": str, "recommendedAction": str} for a finding, using the fast model."""
    result = call_tool(
        system=EXPLAIN_SYSTEM,
        user_text=f"Finding:\n{json.dumps(finding, indent=2)}\n\nExplain it using the explain_finding tool.",
        tool_name="explain_finding",
        tool_description="Give a plain-English explanation and a recommended next step for a finding.",
        schema=EXPLAIN_SCHEMA,
        model_id=FAST_MODEL_ID,
        max_tokens=512,
    )
    return {
        "explanation": str(result.get("explanation", "")).strip(),
        "recommendedAction": str(result.get("recommendedAction", "")).strip(),
    }


# --------------------------------------------------------------------------- additional conflicts

_EVIDENCE = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "enum": ["document", "account"]},
        "docType": {
            "type": ["string", "null"],
            "description": "For document evidence: will|trust|poa|beneficiary_form|other. null for account evidence.",
        },
        "page": {"type": ["integer", "null"], "description": "Document page; null for account evidence."},
        "quote": {
            "type": "string",
            "description": "Copied exactly from a document fact's quote, or an exact value from the client/account record.",
        },
    },
    "required": ["source", "docType", "page", "quote"],
}

CONFLICTS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short neutral title, under 15 words."},
                    "evidence": {"type": "array", "items": _EVIDENCE, "minItems": 1},
                },
                "required": ["title", "evidence"],
            },
        }
    },
    "required": ["findings"],
}

CONFLICTS_SYSTEM = """You review extracted estate-document facts against a client's broker-dealer account records to spot possible inconsistencies an advisor should raise with the client and their attorney.

Look for things simple field-matching rules might miss, for example: a fiduciary or agent who the client record says has died; an account a trust says should be titled in the trust but is registered otherwise; a beneficiary designation that predates and contradicts later documents; a change of state residence since documents were signed; people in account records who are absent from the documents.

Rules:
- Use only the facts and records provided. Never speculate beyond them or state legal conclusions.
- Every finding needs evidence. Document evidence must copy a quote exactly from a document fact, with that fact's docType and page. Account evidence must quote an exact value from the client or account record (page null, docType null).
- Return an empty list if nothing is worth flagging. Prefer fewer, well-supported findings."""


def _flatten(value, prefix="") -> list[str]:
    """Flatten client/account JSON into 'key: value' lines so quotes can be checked against it."""
    if isinstance(value, dict):
        return [line for k, v in value.items() for line in _flatten(v, f"{prefix}{k}.")]
    if isinstance(value, list):
        return [line for v in value for line in _flatten(v, prefix)]
    return [f"{prefix.rstrip('.')}: {value}"]


def _verify_evidence(ev: dict, facts_list: list[dict], record_text: str) -> bool:
    quote = ev.get("quote") or ""
    if ev.get("source") == "account":
        needle = _normalize(quote).strip(" \"'")
        return bool(needle) and needle in _normalize(record_text)

    # Document evidence: check against verified fact quotes from matching documents.
    candidates = [f for f in facts_list if not ev.get("docType") or f.get("docType") == ev.get("docType")]
    for facts in candidates:
        pages: dict[int, list[str]] = {}
        for field in ("dateSigned", "governingState"):
            item = facts.get(field) or {}
            if item.get("quote"):
                pages.setdefault(item["page"], []).append(item["quote"])
        for field in ("people", "assets"):
            for item in facts.get(field, []):
                pages.setdefault(item["page"], []).append(item["quote"])
        page_list = [{"page": p, "text": "\n".join(qs)} for p, qs in pages.items()]
        found = _locate(quote, ev.get("page"), page_list)
        if found is not None:
            ev["page"] = found
            ev["docType"] = facts.get("docType")
            return True
    return False


def find_additional_conflicts(facts_list: list[dict], client: dict, accounts: list[dict]) -> list[dict]:
    """Optional Sonnet pass for conflicts rules may miss. All results have severity "review".

    Findings whose evidence quotes do not verify are dropped (and logged).
    """
    facts_for_model = [
        {k: v for k, v in f.items() if k != "dropped"} for f in facts_list
    ]
    user_text = (
        f"<document_facts>\n{json.dumps(facts_for_model, indent=2)}\n</document_facts>\n\n"
        f"<client_record>\n{json.dumps(client, indent=2)}\n</client_record>\n\n"
        f"<account_records>\n{json.dumps(accounts, indent=2)}\n</account_records>\n\n"
        "Report possible inconsistencies using the report_conflicts tool."
    )
    result = call_tool(
        system=CONFLICTS_SYSTEM,
        user_text=user_text,
        tool_name="report_conflicts",
        tool_description="Report possible inconsistencies between estate documents and account records, with evidence.",
        schema=CONFLICTS_SCHEMA,
        model_id=MODEL_ID,
        max_tokens=4096,
    )

    record_text = "\n".join(_flatten({"client": client, "accounts": accounts}))
    findings = []
    for raw in result.get("findings", []):
        evidence = [dict(ev) for ev in raw.get("evidence", [])]
        bad = [ev for ev in evidence if not _verify_evidence(ev, facts_list, record_text)]
        if not evidence or bad:
            log.warning("Dropped AI finding %r: unverified evidence %s", raw.get("title"), bad)
            continue
        for ev in evidence:
            if ev["source"] == "account":
                ev["docType"], ev["page"] = None, None
        findings.append(
            {
                "findingId": f"AI-{len(findings) + 1}",
                "severity": "review",
                "title": raw.get("title", "").strip(),
                "evidence": evidence,
            }
        )
    return findings

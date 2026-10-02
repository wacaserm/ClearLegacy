"""Plain-English explanations of findings, plus an optional AI pass for conflicts rules may miss.

Owner: Role 1. The AI never decides what the law is. explain() rewrites a rules
finding for an advisor; find_additional_conflicts() only surfaces candidates for
human review, and each one must cite evidence that verifies against validated
facts and the supplied account records.
"""

import json
import logging
import re
from pathlib import Path

from core.bedrock_client import FAST_MODEL_ID, MODEL_ID, call_tool
from core.validation import locate_quote, normalize

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
EXPLANATION_PROMPT = (PROMPTS / "explanation.txt").read_text(encoding="utf-8")
CONFLICTS_PROMPT = (PROMPTS / "conflicts.txt").read_text(encoding="utf-8")

# --------------------------------------------------------------------------- explain

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "At most 2 plain-English sentences describing the difference and why it may matter.",
        },
        "recommendedAction": {
            "type": "string",
            "description": "One sentence: confirm intentions and review with the client and their attorney or appropriate professional.",
        },
    },
    "required": ["explanation", "recommendedAction"],
}


def explain(finding: dict) -> dict:
    """Return {"explanation": str, "recommendedAction": str} for a finding, using the fast model."""
    shown = {k: finding.get(k) for k in ("findingId", "priority", "title", "evidence")}
    result = call_tool(
        system=EXPLANATION_PROMPT,
        user_text=f"<finding>\n{json.dumps(shown, indent=2)}\n</finding>\n\nExplain it using the explain_finding tool.",
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

_NULLABLE = {"type": ["string", "null"]}

CONFLICTS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short neutral title, under 15 words."},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "sourceType": {"type": "string", "enum": ["document", "account"]},
                                "sourceId": {"type": "string", "description": "Document sourceId, accountId, or clientId."},
                                "location": {**_NULLABLE, "description": "Document evidence only."},
                                "quote": {**_NULLABLE, "description": "Document evidence only: exact quote from a fact."},
                                "field": {**_NULLABLE, "description": "Account evidence only: field name in the record."},
                                "value": {**_NULLABLE, "description": "Account evidence only: exact value from that field."},
                            },
                            "required": ["sourceType", "sourceId", "location", "quote", "field", "value"],
                        },
                    },
                },
                "required": ["title", "evidence"],
            },
        }
    },
    "required": ["findings"],
}


def _leaves(value, keys: set) -> list[str]:
    """Collect normalized scalar values (and dict keys into `keys`) under a record field."""
    if isinstance(value, dict):
        keys.update(normalize(k) for k in value)
        return [leaf for v in value.values() for leaf in _leaves(v, keys)]
    if isinstance(value, list):
        return [leaf for v in value for leaf in _leaves(v, keys)]
    return [normalize(str(value))]


def _resolve(record: dict, field: str):
    """Resolve a field name, allowing dotted paths like 'trustedContact.name'."""
    value = record
    for part in (field or "").split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _verify_document_evidence(ev: dict, facts_list: list[dict]) -> dict | None:
    for facts in facts_list:
        if facts.get("sourceId") != ev.get("sourceId"):
            continue
        by_location: dict[str, list[str]] = {}
        for fact in facts.get("facts", []):
            by_location.setdefault(fact["location"], []).append(fact["quote"])
        sections = [{"location": loc, "text": "\n".join(q)} for loc, q in by_location.items()]
        found = locate_quote(ev.get("quote") or "", ev.get("location"), sections)
        if found is not None:
            return {"sourceType": "document", "sourceId": ev["sourceId"], "location": found, "quote": ev["quote"]}
    return None


def _verify_account_evidence(ev: dict, client: dict, accounts: list[dict]) -> dict | None:
    records = {a.get("accountId"): a for a in accounts}
    if client.get("clientId"):
        records[client["clientId"]] = client
    record = records.get(ev.get("sourceId"))
    field = ev.get("field")
    target = _resolve(record, field) if record is not None else None
    if target is None or not normalize(ev.get("value") or ""):
        return None
    # A combined value like "Linda Johnson, former spouse, 100%" verifies only if
    # every comma/semicolon-separated piece is found in the field's actual values.
    keys: set = set()
    leaves = _leaves(target, keys)
    for piece in re.split(r"[,;]", normalize(ev["value"])):
        piece = piece.strip(" \"'")
        for key in keys:  # tolerate "recordedDate 2009-05-11" style labels
            if piece.startswith(key + " ") or piece.startswith(key + ":"):
                piece = piece[len(key) + 1:].strip(" :")
                break
        if piece and not any(piece in leaf for leaf in leaves):
            return None
    return {"sourceType": "account", "sourceId": ev["sourceId"], "field": field, "value": ev["value"]}


def find_additional_conflicts(facts_list: list[dict], client: dict, accounts: list[dict]) -> list[dict]:
    """Optional Sonnet pass for conflicts rules may miss. All results have priority "review".

    facts_list holds validated extraction results. A finding is dropped (and
    logged) if any of its evidence fails to verify.
    """
    facts_for_model = [
        {"sourceId": f.get("sourceId"), "docType": f.get("docType"), "facts": f.get("facts", [])}
        for f in facts_list
    ]
    user_text = (
        f"<document_facts>\n{json.dumps(facts_for_model, indent=2)}\n</document_facts>\n\n"
        f"<client_record>\n{json.dumps(client, indent=2)}\n</client_record>\n\n"
        f"<account_records>\n{json.dumps(accounts, indent=2)}\n</account_records>\n\n"
        "Report possible inconsistencies using the report_conflicts tool."
    )
    result = call_tool(
        system=CONFLICTS_PROMPT,
        user_text=user_text,
        tool_name="report_conflicts",
        tool_description="Report possible inconsistencies between documents and account records, with evidence.",
        schema=CONFLICTS_SCHEMA,
        model_id=MODEL_ID,
        max_tokens=4096,
    )

    findings = []
    for raw in result.get("findings", []):
        evidence = []
        for ev in raw.get("evidence", []):
            if ev.get("sourceType") == "account":
                checked = _verify_account_evidence(ev, client, accounts)
            else:
                checked = _verify_document_evidence(ev, facts_list)
            if checked is None:
                log.warning("Dropped AI finding %r: unverified evidence from %s", raw.get("title"), ev.get("sourceId"))
                evidence = []
                break
            evidence.append(checked)
        if not evidence:
            continue
        findings.append(
            {
                "findingId": f"AI-{len(findings) + 1}",
                "priority": "review",
                "title": str(raw.get("title", "")).strip(),
                "evidence": evidence,
            }
        )
    return findings

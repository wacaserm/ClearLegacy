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
SUMMARY_PROMPT = (PROMPTS / "summary.txt").read_text(encoding="utf-8")

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
    """Return the finding with "explanation" and "recommendedAction" added (fast model)."""
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
    explanation = _first_sentences(result.get("explanation"), 2)
    action = _first_sentences(result.get("recommendedAction"), 1)
    if not explanation or not action:
        log.warning("explain() got an empty field for %s; using safe fallback text", finding.get("findingId"))
    # Return the finding with the two fields added, so callers that replace a
    # finding with explain()'s result keep its id, title, priority, and evidence.
    return {
        **finding,
        "explanation": explanation or str(finding.get("title") or "").strip(),
        "recommendedAction": action or DEFAULT_ACTION,
    }


DEFAULT_ACTION = (
    "Confirm the client's intentions and review this item with the client and their attorney "
    "or other appropriate professional."
)


def _first_sentences(text, n: int) -> str:
    """Trim model text to at most n sentences."""
    if not isinstance(text, str):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:n]).strip()


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


def verify_document_evidence(ev: dict, facts_list: list[dict]) -> dict | None:
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


def verify_account_evidence(ev: dict, client: dict, accounts: list[dict]) -> dict | None:
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
        if not piece or any(piece in leaf for leaf in leaves):
            continue
        if piece.endswith("%") and piece[:-1].strip() in leaves:  # "100%" vs numeric 100
            continue
        # Allow a short label like "recorded 2009-05-11", but only if the rest is an exact value.
        label = re.match(r"^[a-z]+(?: [a-z]+)? (.+)$", piece)
        if not (label and label.group(1) in leaves):
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
    raw_findings = result.get("findings")
    for raw in raw_findings if isinstance(raw_findings, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("evidence"), list):
            log.warning("Skipped malformed AI finding")
            continue
        evidence = []
        for ev in raw["evidence"]:
            if not isinstance(ev, dict):
                evidence = []
                break
            if ev.get("sourceType") == "account":
                checked = verify_account_evidence(ev, client, accounts)
            else:
                checked = verify_document_evidence(ev, facts_list)
            if checked is None:
                log.warning("Dropped AI finding %r: unverified evidence %s %s=%r", raw.get("title"),
                            ev.get("sourceId"), ev.get("field"), ev.get("value") or ev.get("quote"))
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


def verify_evidence(ev, facts_list: list[dict], client: dict, accounts: list[dict]) -> dict | None:
    """Return the cleaned evidence item if it verifies, else None."""
    if not isinstance(ev, dict):
        return None
    if ev.get("sourceType") == "account":
        return verify_account_evidence(ev, client, accounts)
    return verify_document_evidence(ev, facts_list)


# --------------------------------------------------------------------------- case summary

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "description": "At most 3 plain-English sentences."}},
    "required": ["summary"],
}

NO_FINDINGS_SUMMARY = (
    "No potential inconsistencies were flagged between the supplied documents and account records. "
    "This covers only the documents and records provided."
)


def summarize_case(client: dict, findings: list[dict]) -> dict:
    """Return {"summary": str}: a short advisor-facing overview of the findings (fast model)."""
    if not findings:
        return {"summary": NO_FINDINGS_SUMMARY}
    shown = [
        {k: f.get(k) for k in ("findingId", "priority", "title", "explanation") if f.get(k)}
        for f in findings
    ]
    result = call_tool(
        system=SUMMARY_PROMPT,
        user_text=(
            f"<client>{json.dumps({'name': client.get('name')})}</client>\n"
            f"<findings>\n{json.dumps(shown, indent=2)}\n</findings>\n\n"
            "Write the case summary using the write_case_summary tool."
        ),
        tool_name="write_case_summary",
        tool_description="Write a short advisor-facing summary of review findings.",
        schema=SUMMARY_SCHEMA,
        model_id=FAST_MODEL_ID,
        max_tokens=512,
    )
    summary = _first_sentences(result.get("summary"), 3)
    return {"summary": summary or f"{len(findings)} item(s) flagged for review with the client and their attorney."}

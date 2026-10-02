"""Read-only advisor Q&A over one client's validated facts, accounts, and findings.

Owner: Role 1. The assistant only reads data passed in; it has no tools that
change anything. Every citation must verify against validated facts or actual
account values, and an answer with no verified support is withheld.
"""

import json
import logging
import re
from pathlib import Path

from core.bedrock_client import MODEL_ID, call_tool
from core.explain import CONFLICTS_SCHEMA, _first_sentences, verify_evidence

log = logging.getLogger(__name__)

ASSISTANT_PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "assistant.txt").read_text(encoding="utf-8")

_EVIDENCE = CONFLICTS_SCHEMA["properties"]["findings"]["items"]["properties"]["evidence"]["items"]

ANSWER_SCHEMA = {
    "type": "object",
    # Citations and canAnswer come first so the model fills them before the
    # free-text answer; text that leaks past the answer can't swallow them.
    "properties": {
        "citations": {"type": "array", "items": _EVIDENCE},
        "canAnswer": {"type": "boolean", "description": "False if the provided data does not answer the question."},
        "answer": {"type": "string", "description": "At most 4 plain-English sentences."},
    },
    "required": ["citations", "canAnswer", "answer"],
}

UNSUPPORTED_ANSWER = (
    "I couldn't find support for an answer in the supplied documents and account records."
)


_MARKUP = re.compile(r"</?(?:answer|parameter|invoke|citations)\b.*", re.S)


def _strip_markup(text) -> str:
    """Remove tool-call markup that sometimes leaks into a string field."""
    return _MARKUP.sub("", text).strip() if isinstance(text, str) else ""


def answer_question(
    question: str,
    facts_list: list[dict],
    client: dict,
    accounts: list[dict],
    findings: list[dict] | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Answer an advisor's question from the supplied data only.

    history: optional prior turns [{"question": str, "answer": str}] for follow-ups.
    Returns {"answer": str, "canAnswer": bool, "citations": [evidence], "droppedCitations": int}.
    """
    facts_for_model = [
        {"sourceId": f.get("sourceId"), "docType": f.get("docType"), "facts": f.get("facts", [])}
        for f in facts_list
    ]
    findings_for_model = [
        {k: f.get(k) for k in ("findingId", "priority", "title", "explanation") if f.get(k)}
        for f in findings or []
    ]
    turns = [{"question": t.get("question"), "answer": t.get("answer")} for t in (history or [])[-5:]]
    user_text = (
        f"<document_facts>\n{json.dumps(facts_for_model, indent=2)}\n</document_facts>\n\n"
        f"<client_record>\n{json.dumps(client, indent=2)}\n</client_record>\n\n"
        f"<account_records>\n{json.dumps(accounts, indent=2)}\n</account_records>\n\n"
        f"<findings>\n{json.dumps(findings_for_model, indent=2)}\n</findings>\n\n"
        f"<conversation>\n{json.dumps(turns, indent=2)}\n</conversation>\n\n"
        f"<question>{question}</question>\n\nAnswer using the answer_with_citations tool."
    )
    reply = None
    for attempt in range(2):
        result = call_tool(
            system=ASSISTANT_PROMPT,
            user_text=user_text,
            tool_name="answer_with_citations",
            tool_description="Answer the advisor's question with citations to document facts and account records.",
            schema=ANSWER_SCHEMA,
            model_id=MODEL_ID,
            max_tokens=2048,
        )
        reply = _checked_reply(result, facts_list, client, accounts)
        if reply is not None:
            return reply
        # Occasionally the model's citations get lost; one retry before withholding.
        log.warning("Assistant answer had no verified support (attempt %d)", attempt + 1)
    return {"answer": UNSUPPORTED_ANSWER, "canAnswer": False, "citations": [], "droppedCitations": 0}


def _checked_reply(result: dict, facts_list, client, accounts) -> dict | None:
    """Return a displayable reply, or None if the answer has no verified support."""
    raw_citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    citations = [c for c in (verify_evidence(ev, facts_list, client, accounts) for ev in raw_citations) if c]
    dropped = len(raw_citations) - len(citations)
    if dropped:
        log.warning("Dropped %d unverified citation(s) from assistant answer", dropped)

    answer = _first_sentences(_strip_markup(result.get("answer")), 4)
    if citations and answer:
        return {"answer": answer, "canAnswer": True, "citations": citations, "droppedCitations": dropped}
    if result.get("canAnswer") is False and answer:
        # The model explicitly says the data can't answer; show its explanation of what's missing.
        return {"answer": answer, "canAnswer": False, "citations": [], "droppedCitations": dropped}
    return None

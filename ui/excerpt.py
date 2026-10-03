"""Find the document passage around a cited quote and highlight the quote (read-only, escaped)."""

import re

from ui.html import esc

CONTEXT_CHARS = 420  # characters of surrounding text to show on each side, at most


def _squash(text) -> str:
    return " ".join(str(text or "").split())


def find_context(quote, source_id, location, documents) -> str | None:
    """Return the section text that contains the quote, or None.

    documents is analysis["documents"] (the read text the adapter keeps for the session).
    The cited location is tried first, then every section of the same document.
    """
    needle = _squash(quote).lower()
    if not needle:
        return None
    for document in documents or []:
        if source_id and document.get("sourceId") != source_id:
            continue
        sections = document.get("sections") or []
        ordered = [s for s in sections if s.get("location") == location] + \
                  [s for s in sections if s.get("location") != location]
        for section in ordered:
            text = _squash(section.get("text"))
            if needle in text.lower():
                return text
    return None


def highlight_html(context, quote) -> str:
    """Escaped passage with the quote wrapped in <mark>; the quote alone if it isn't in the passage.

    Matching is case-insensitive and whitespace-normalized. All text is escaped before the
    highlight markup is inserted, because document text is untrusted.
    """
    quote_text = _squash(quote)
    context_text = _squash(context)
    start = context_text.lower().find(quote_text.lower()) if quote_text and context_text else -1
    if start < 0:
        return f'<mark class="cl-hl">{esc(quote_text)}</mark>'
    end = start + len(quote_text)
    left = context_text[max(0, start - CONTEXT_CHARS):start]
    right = context_text[end:end + CONTEXT_CHARS]
    if start > CONTEXT_CHARS:
        left = "…" + left[left.find(" ") + 1:] if " " in left else "…" + left
    if len(context_text) - end > CONTEXT_CHARS:
        right = right[:right.rfind(" ")] + "…" if " " in right else right + "…"
    return f'{esc(left)}<mark class="cl-hl">{esc(context_text[start:end])}</mark>{esc(right)}'


def short_title(title, limit=72) -> str:
    text = _squash(title)
    return text if len(text) <= limit else text[: text.rfind(" ", 0, limit)] + "…"


_ACCOUNT_ID = re.compile(r"\bDEMO-[A-Z0-9-]+\b")


def accounts_in(finding) -> set:
    """Account IDs a finding refers to, from its account evidence or its title."""
    ids = {e.get("sourceId") for e in finding.get("evidence", []) or []
           if isinstance(e, dict) and e.get("sourceType") == "account" and e.get("sourceId")}
    ids.update(_ACCOUNT_ID.findall(str(finding.get("title", ""))))
    return ids

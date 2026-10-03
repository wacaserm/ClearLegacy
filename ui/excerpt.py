"""Find the document passage around a cited quote and highlight the quote (read-only, escaped)."""

import re

from ui.html import esc

CONTEXT_CHARS = 220  # characters after the quote, at most
LEFT_CHARS = 60  # characters before the quote, at most


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
            # Keep line breaks (they mark document lines) but tidy spaces within each line.
            lines = [" ".join(line.split()) for line in str(section.get("text") or "").splitlines() if line.strip()]
            text = "\n".join(lines)
            if needle in " ".join(text.split()).lower():
                return text
    return None


def highlight_html(context, quote) -> str:
    """Escaped passage with the quote wrapped in <mark>; the quote alone if it isn't in the passage.

    Matching is case-insensitive and whitespace-normalized. Context is sentence-based (PDF line
    breaks often fall mid-sentence): up to LEFT_CHARS before the quote, starting at a sentence
    when one begins in that window, and through the end of the next sentence after it.
    All text is escaped before the highlight markup is inserted; document text is untrusted.
    """
    quote_text = _squash(quote)
    flat = _squash(context)
    start = flat.lower().find(quote_text.lower()) if quote_text and flat else -1
    if start < 0:
        return f'<mark class="cl-hl">{esc(quote_text)}</mark>'
    end = start + len(quote_text)

    window_start = max(0, start - LEFT_CHARS)
    left = flat[window_start:start]
    head = left.rstrip()
    head = head[:-1] if head.endswith((".", "?", "!")) else head  # ignore the sentence end right at the quote
    sentence_starts = [m.end() for m in re.finditer(r"[.?!]\s+", head)]
    if sentence_starts:
        left = left[sentence_starts[-1]:]
        prefix = ""
    elif window_start > 0:
        left = left[left.find(" ") + 1:] if " " in left else left
        prefix = "… "
    else:
        prefix = ""

    after = flat[end:end + CONTEXT_CHARS]
    stop = re.search(r"[.?!](\s|$)", after)
    right = after[: stop.end()].rstrip() if stop else (after[: after.rfind(" ")] if " " in after else after)
    suffix = " …" if end + len(right) < len(flat) - 1 else ""
    return f'{esc(prefix + left)}<mark class="cl-hl">{esc(flat[start:end])}</mark>{esc(right + suffix)}'


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

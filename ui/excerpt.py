"""Find the document passage around a cited quote and highlight the quote (read-only, escaped)."""

import re

from ui.html import esc

CONTEXT_CHARS = 220  # characters of surrounding text to show on each side, at most


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

    Matching is case-insensitive and whitespace-normalized. The passage keeps one sentence or
    document line before and after the quote. All text is escaped before the highlight markup
    is inserted, because document text is untrusted.
    """
    quote_text = _squash(quote)
    lined = "\n".join(" ".join(line.split()) for line in str(context or "").splitlines() if line.strip())
    flat = lined.replace("\n", " ")  # same length as `lined`, so positions line up
    start = flat.lower().find(quote_text.lower()) if quote_text and flat else -1
    if start < 0:
        return f'<mark class="cl-hl">{esc(quote_text)}</mark>'
    end = start + len(quote_text)

    def boundaries(text):
        return [i + 1 for i, ch in enumerate(text) if ch == "\n"] + \
               [m.end() for m in re.finditer(r"[.?!]\s", text)]

    before = [b for b in boundaries(lined[:start]) if b < start - 1]  # ignore the boundary right at the quote
    left_start = max(before) if before else 0  # start of the line or sentence before the quote
    left_start = max(left_start, start - CONTEXT_CHARS)
    after = [b for b in boundaries(lined[end:]) if b > 1]
    right_end = end + (min(after) if after else len(lined) - end)
    right_end = min(right_end, end + CONTEXT_CHARS)
    left = flat[left_start:start]
    right = flat[end:right_end].rstrip()
    prefix = "… " if left_start > 0 else ""
    suffix = " …" if right_end < len(flat) else ""
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

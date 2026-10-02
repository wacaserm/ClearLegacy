"""Evidence validation: keep only facts whose quote is found in the source document.

Owner: Role 2 (initial quote-grounding implementation contributed by Role 1).

Quote validation reduces unsupported outputs; it does not prove legal correctness.
"""

import copy
import logging
import re

log = logging.getLogger(__name__)

_QUOTE_CHARS = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
)
_ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")


def normalize(text: str) -> str:
    """Lowercase, straighten quotes/dashes, and collapse whitespace."""
    text = (text or "").translate(_QUOTE_CHARS).lower()
    return re.sub(r"\s+", " ", text).strip()


def _fragments(quote: str) -> list[str]:
    """Split a quote on ellipses; every fragment must be verbatim document text."""
    parts = [p.strip(" \"'") for p in _ELLIPSIS.split(normalize(quote))]
    return [p for p in parts if p]


def _contains_in_order(text: str, fragments: list[str]) -> bool:
    pos = 0
    for frag in fragments:
        pos = text.find(frag, pos)
        if pos < 0:
            return False
        pos += len(frag)
    return True


def locate_quote(quote: str, claimed_location, sections: list[dict]):
    """Return the location of the section containing the quote, preferring the claimed one.

    A quote shortened with "..." matches only if every fragment appears, in order,
    within one section. Returns None if the quote is not found.
    """
    fragments = _fragments(quote)
    if not fragments:
        return None
    by_location = {s["location"]: normalize(s["text"]) for s in sections}
    if claimed_location in by_location and _contains_in_order(by_location[claimed_location], fragments):
        return claimed_location
    for location, text in by_location.items():
        if _contains_in_order(text, fragments):
            return location
    return None


def validate_facts(facts: dict, document: dict) -> dict:
    """Drop facts whose quote is not in the document and correct wrong locations.

    Returns a copy of facts. Each dropped fact adds a plain-text message to
    "warnings" and the fact itself to "excludedFacts".
    """
    out = copy.deepcopy(facts)
    sections = document.get("sections", [])
    warnings = list(out.get("warnings", []))
    excluded = list(out.get("excludedFacts", []))
    kept = []
    for fact in out.get("facts", []):
        found = locate_quote(fact.get("quote") or "", fact.get("location"), sections)
        if found is None:
            warnings.append(
                f"Excluded unsupported fact ({fact.get('field')}: {fact.get('value')}): "
                f"quote not found in {out.get('sourceId')}"
            )
            excluded.append(fact)
            # Log field and source only; avoid raw document content in diagnostic logs.
            log.warning("Excluded unsupported %s fact from %s", fact.get("field"), out.get("sourceId"))
            continue
        if found != fact.get("location"):
            log.info("Corrected %s location %r -> %r", fact.get("field"), fact.get("location"), found)
            fact["location"] = found
        kept.append(fact)
    out["facts"] = kept
    out["warnings"] = warnings
    out["excludedFacts"] = excluded
    return out

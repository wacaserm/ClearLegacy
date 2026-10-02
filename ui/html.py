"""Small helpers for rendering escaped HTML. Every dynamic value goes through esc()."""

import html
import json

import streamlit as st

PRIORITY_ORDER = {"critical": 0, "high": 1, "review": 2}
PRIORITY_LABELS = {"critical": "Critical", "high": "High", "review": "Review"}

STATUS_PILLS = {
    "not_analyzed": ("Not analyzed", "neutral"),
    "processing": ("Analyzing", "brand"),
    "review_needed": ("Review needed", "high"),
    "needs_information": ("Needs information", "review"),
    "no_discrepancies_found": ("No discrepancies", "clear"),
    "failed": ("Failed", "critical"),
    "outdated": ("Outdated", "neutral"),
}

DOC_TYPE_LABELS = {
    "will": "Will",
    "trust": "Trust",
    "poa": "POA",
    "planning_summary": "Planning summary",
    "account_records": "Account records",
    "beneficiary_form": "Beneficiary form",
}


def esc(value) -> str:
    """Escape any value for safe interpolation into HTML (document text is untrusted)."""
    return html.escape("" if value is None else str(value), quote=True)


def render(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def pill(label: str, tone: str = "neutral", plain: bool = False) -> str:
    return f'<span class="cl-pill {esc(tone)}{" plain" if plain else ""}">{esc(label)}</span>'


def priority_key(priority) -> str:
    value = str(priority or "review").lower()
    return value if value in PRIORITY_ORDER else "review"


def priority_pill(priority) -> str:
    key = priority_key(priority)
    return pill(PRIORITY_LABELS[key], key)


def status_pill(status) -> str:
    label, tone = STATUS_PILLS.get(status, STATUS_PILLS["not_analyzed"])
    return pill(label, tone)


def humanize_field(field) -> str:
    """primaryBeneficiaries -> Primary beneficiaries; todBeneficiaries -> TOD beneficiaries."""
    text = str(field or "Record")
    out = []
    for index, char in enumerate(text):
        if char.isupper() and index and not text[index - 1].isupper():
            out.append(" ")
        out.append(char)
    words = "".join(out).replace("_", " ").split()
    if not words:
        return "Record"
    words = [w if w.isupper() and len(w) > 1 else w.lower() for w in words]
    words[0] = words[0][0].upper() + words[0][1:]
    return " ".join(words)


def parse_record_value(value):
    """Account evidence values are often JSON text; return a list of dict rows or None."""
    if isinstance(value, (list, dict)):
        data = value
    else:
        try:
            data = json.loads(value)
        except (TypeError, ValueError):
            return None
    if isinstance(data, dict):
        data = [data]
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return data
    return None


def format_percentage(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}%"
    text = str(value)
    return text if text.endswith("%") else f"{text}%"


def beneficiary_text(rows) -> str:
    """'Taylor Morgan (former spouse) · 100%' lines for a beneficiaries list (escaped)."""
    if not rows:
        return '<span class="sub">None listed</span>'
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            lines.append(esc(row))
            continue
        name = esc(row.get("name") or "Unnamed")
        relationship = row.get("relationship")
        share = format_percentage(row.get("percentage", row.get("allocation")))
        rel = f' <span class="sub" style="display:inline">({esc(relationship)})</span>' if relationship else ""
        num = f' · <span class="cl-num">{esc(share)}</span>' if share else ""
        lines.append(f"{name}{rel}{num}")
    return "<br>".join(lines)

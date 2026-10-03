import streamlit as st

from core import config
from ui.html import esc, render

SHOW_DETAILS_KEY = "clearlegacy_show_system_details"
TECH_WARNINGS_KEY = "clearlegacy_tech_warnings"

# Technical fallback messages (from core/) -> wording for advisors. Order matters: first match wins.
_ADVISOR_WORDING = (
    ("DynamoDB unavailable", "Working offline: decisions aren't being saved to the firm record."),
    ("in DynamoDB; using local JSON", "Working offline: client records are loading from a local copy."),
    ("S3 storage unavailable", "Document copies couldn't be saved to secure storage. The review can continue."),
    ("OCR unavailable", "Some scanned pages couldn't be read. Upload a text-based copy if information is missing."),
    ("Temporary OCR file", "A temporary scan copy couldn't be cleaned up. The review is not affected."),
    ("Comprehend unavailable", "Personal information is being protected with a simpler method right now."),
)


def advisor_message(technical):
    """Advisor-friendly wording for an AWS fallback message, or None if it isn't one."""
    text = str(technical)
    for marker, wording in _ADVISOR_WORDING:
        if marker in text:
            return wording
    return None


def remember_technical(message):
    """Keep the technical detail for the System details panel."""
    stored = st.session_state.setdefault(TECH_WARNINGS_KEY, [])
    if message not in stored:
        stored.append(message)
        del stored[:-20]


def show_system_details():
    return bool(st.session_state.get(SHOW_DETAILS_KEY, False))


def render_sidebar_footer():
    """Quiet privacy label and the 'Show system details' toggle."""
    if config.pii_masking():
        render('<p class="cl-small" style="margin:0 0 8px">Personal information protected</p>')
    st.toggle("Show system details", key=SHOW_DETAILS_KEY)


def render_aws_warnings():
    """Fallback warnings in advisor wording; technical detail goes to System details."""
    shown = []
    for warning in config.drain_warnings():
        remember_technical(warning)
        message = advisor_message(warning) or "Some services are temporarily unavailable. The review can continue."
        if message not in shown:
            shown.append(message)
            render(f'<div class="cl-notice warn">{esc(message)}</div>')


def usage_parts(analysis):
    """Models, time, tokens, and estimated cost for one analysis."""
    usage = (analysis or {}).get("usage") or {}
    models = usage.get("models") or {}
    parts = []
    if models:
        names = ["Claude Sonnet 5" if "sonnet" in m else "Claude Haiku 4.5" if "haiku" in m else m for m in models]
        parts.append("Models: " + ", ".join(dict.fromkeys(names)) + " on Amazon Bedrock")
    if (analysis or {}).get("elapsedSeconds") is not None:
        parts.append(f"Time: {analysis['elapsedSeconds']:.0f}s")
    if usage.get("estimatedCostUSD") is not None and models:
        tokens = sum(m.get("inputTokens", 0) + m.get("outputTokens", 0) for m in models.values())
        parts.append(f"Tokens: {tokens:,}")
        parts.append(f"Est. cost: ${usage['estimatedCostUSD']:.3f} (estimate)")
    return parts


def render_system_details(analysis=None):
    """Technical panel, shown only when the sidebar toggle is on."""
    if not show_system_details():
        return
    settings = config.summary()
    storage = "DynamoDB" if settings["storage"] == "dynamodb" else "Local JSON"
    backends = [f"Storage: {storage}", f"OCR: {'Amazon Textract' if settings['textract'] else 'off'}",
                f"Documents: {'Amazon S3 (encrypted)' if settings['s3'] else 'local only'}",
                f"PII masking: {'Amazon Comprehend' if settings['piiMasking'] else 'off'}"]
    rows = ['<p class="cl-label">System details</p>',
            f'<p class="cl-small">{esc(" · ".join(backends))}</p>']
    parts = usage_parts(analysis)
    if parts:
        rows.append('<p class="cl-small" style="margin-top:8px"><b>Last analysis</b> · ' + esc(" · ".join(parts)) + "</p>")
    technical = st.session_state.get(TECH_WARNINGS_KEY, [])
    if technical:
        rows.append('<p class="cl-small" style="margin-top:8px"><b>Service messages</b></p>')
        rows.extend(f'<p class="cl-small" style="margin:2px 0">{esc(m)}</p>' for m in technical)
    render('<div class="cl-card quiet" style="margin-top:24px">' + "".join(rows) + "</div>")

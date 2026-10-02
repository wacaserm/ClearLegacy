import streamlit as st

from core import config
from ui.html import esc, pill, render


def render_aws_status_sidebar():
    """Quiet backend line and PII pill for the sidebar footer."""
    settings = config.summary()
    storage = "DynamoDB" if settings["storage"] == "dynamodb" else "Local JSON"
    parts = [f"Storage: {storage}", f"OCR: {'Amazon Textract' if settings['textract'] else 'off'}",
             f"Documents: {'Amazon S3 (encrypted)' if settings['s3'] else 'local only'}"]
    render(f'<p class="cl-small" style="line-height:1.7;margin:0 0 8px">{esc(" · ".join(parts))}</p>')
    if settings["piiMasking"]:
        render(pill("PII masking on", "brand"))


def render_aws_warnings():
    """AWS fallback warnings, shown in the main area so they stay visible."""
    for warning in config.drain_warnings():
        render(f'<div class="cl-notice warn">{esc(warning)}</div>')


def render_aws_status():
    """Backwards-compatible entry point (sidebar line + main-area warnings)."""
    render_aws_warnings()

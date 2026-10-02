import streamlit as st

from core import config
from ui import compat


def render_aws_status():
    """One line showing which storage/OCR/S3 backends are active, plus any AWS fallback warnings."""
    settings = config.summary()
    storage = "DynamoDB" if settings["storage"] == "dynamodb" else "local JSON"
    parts = [f"Storage: {storage}", f"OCR: {'Amazon Textract' if settings['textract'] else 'off'}",
             f"Documents: {'Amazon S3 (encrypted)' if settings['s3'] else 'local only'}"]
    columns = st.columns([5, 1])
    with columns[0]:
        st.caption(" · ".join(parts))
    if settings["piiMasking"]:
        with columns[1]:
            compat.badge("PII masking on", color="green")
    for warning in config.drain_warnings():
        st.warning(warning)

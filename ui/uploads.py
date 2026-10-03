import streamlit as st

from services import gui_adapter
from ui import compat
from ui.html import DOC_TYPE_LABELS, esc, render


def _type_label(document, preview):
    doc_type = (preview or {}).get("docType")
    if doc_type in DOC_TYPE_LABELS:
        return DOC_TYPE_LABELS[doc_type]
    return "Account records" if document["category"] == "account" else "Planning document"


def render_uploads(client_id, backend):
    """Documents card. Returns (documents, previews, extraction_errors, card) so the
    Analyze button can be rendered inside the same card."""
    file_types = gui_adapter.supported_upload_types(backend)
    card = st.container(border=True, key=f"docs_card_{client_id}")
    with card:
        render('<p class="cl-section">Documents</p>'
               '<p class="cl-muted" style="margin:-4px 0 12px">Upload the client\'s planning documents and the account '
               'records to compare. Several planning documents can be uploaded together.</p>')
        planning_column, account_column = st.columns(2, gap="medium")
        with planning_column:
            render('<p class="cl-label">Planning documents · will, trust, POA, summary</p>')
            planning_files = st.file_uploader(
                "Planning documents", type=file_types, accept_multiple_files=True,
                key=f"planning_uploads_{client_id}", label_visibility="collapsed",
            )
        with account_column:
            render('<p class="cl-label">Account records</p>')
            account_files = st.file_uploader(
                "Account records", type=file_types, accept_multiple_files=True,
                key=f"account_uploads_{client_id}", label_visibility="collapsed",
            )

        documents = []
        for file in planning_files or []:
            documents.append({"filename": file.name, "file_bytes": file.getvalue(), "category": "planning"})
        for file in account_files or []:
            documents.append({"filename": file.name, "file_bytes": file.getvalue(), "category": "account"})

        previews, extraction_errors = gui_adapter.preview_documents(documents, backend)
        by_name = {preview.get("filename"): preview for preview in previews}
        error_names = {name for name, _ in extraction_errors}

        if documents:
            rows = []
            for document in documents:
                preview = by_name.get(document["filename"])
                tags = []
                if preview and preview.get("ocrPages"):
                    tags.append('<span class="cl-tag" title="Text recognized from a scanned page">Scanned: text recognized</span>')
                if document["filename"] in error_names:
                    tags.append('<span class="cl-pill critical">Could not read</span>')
                elif preview and preview.get("status") not in (None, "ok"):
                    tags.append(f'<span class="cl-pill high">{esc(str(preview.get("status")).replace("_", " "))}</span>')
                rows.append(
                    f'<div class="cl-file"><span class="cl-file-name">{esc(document["filename"])}</span>'
                    f'<span class="cl-file-meta">{"".join(tags)}<span class="cl-small">{esc(_type_label(document, preview))}</span></span></div>'
                )
            render('<div class="cl-files">' + "".join(rows) + "</div>")
        else:
            render('<p class="cl-small" style="margin-top:4px">PDF and DOCX are supported'
                   + (", plus scanned images through Textract" if any(t in file_types for t in ("png", "jpg")) else "")
                   + ".</p>")

        if documents and not callable(getattr(backend.get("reader"), "read_document", None)):
            render('<div class="cl-notice">Text previews are unavailable until the document reader is connected.</div>')
        for filename, message in extraction_errors:
            render(f'<div class="cl-notice error"><b>{esc(filename)}</b>: {esc(message)}</div>')
        if previews:
            with st.expander("Preview extracted text and source locations"):
                for filename, preview in by_name.items():
                    st.markdown(f"**{filename}**")
                    for section in preview.get("sections", []):
                        st.caption(section.get("location", "Source location not provided"))
                        st.text(section.get("text", ""))
    return documents, previews, extraction_errors, card


def render_analyze_button(client_id, documents, extraction_errors, backend, processing):
    pipeline_available = callable(getattr(backend.get("pipeline"), "analyze", None))
    enabled = bool(documents) and not extraction_errors and pipeline_available and not processing
    hint_column, button_column = st.columns([4, 1], vertical_alignment="center")
    with hint_column:
        if not documents:
            hint = "Add at least one document to enable analysis."
        elif not pipeline_available:
            hint = "Analysis is unavailable until the analysis pipeline is connected."
        elif extraction_errors:
            hint = "Resolve the file errors above before analysis."
        elif processing:
            hint = "Analysis is already in progress."
        else:
            hint = "Bedrock is called only when you click Analyze. Results stay for this session."
        render(f'<p class="cl-small" style="margin:0">{esc(hint)}</p>')
    with button_column:
        return compat.button("Analyze", key=f"analyze_{client_id}", stretch=True, type="primary", disabled=not enabled)

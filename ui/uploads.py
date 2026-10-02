import streamlit as st

from services import gui_adapter


def render_uploads(client_id, backend):
    file_types = gui_adapter.supported_upload_types(backend)
    planning_column, account_column = st.columns(2)
    with planning_column:
        with st.container(border=True):
            st.markdown("**Planning documents**")
            planning_files = st.file_uploader(
                "Upload planning documents",
                type=file_types,
                accept_multiple_files=True,
                key=f"planning_uploads_{client_id}",
            )
    with account_column:
        with st.container(border=True):
            st.markdown("**Account records**")
            account_files = st.file_uploader(
                "Upload account records",
                type=file_types,
                accept_multiple_files=True,
                key=f"account_uploads_{client_id}",
            )

    documents = []
    for file in planning_files or []:
        documents.append({"filename": file.name, "file_bytes": file.getvalue(), "category": "planning"})
    for file in account_files or []:
        documents.append({"filename": file.name, "file_bytes": file.getvalue(), "category": "account"})
    if documents:
        for document in documents:
            st.caption(f"{document['category'].title()} · {document['filename']}")
        st.caption("Selected files remain in this Streamlit session until submitted. No S3 storage is implied.")
    else:
        st.caption("PDF and DOCX are supported. CSV appears only when the connected reader advertises support.")

    previews, extraction_errors = gui_adapter.preview_documents(documents, backend)
    preview_by_name = {preview.get("filename"): preview for preview in previews}
    if documents and not callable(getattr(backend.get("reader"), "read_document", None)):
        st.info("Text previews are unavailable until core.document_reader.read_document is connected.")
    for filename, message in extraction_errors:
        st.error(f"{filename}: {message}")
    if previews:
        with st.expander("Preview extracted text and source locations"):
            for filename, preview in preview_by_name.items():
                st.markdown(f"**{filename}**")
                for section in preview.get("sections", []):
                    st.caption(section.get("location", "Source location not provided"))
                    st.text(section.get("text", ""))
    return documents, previews, extraction_errors


def render_analyze_button(client_id, documents, extraction_errors, backend, processing):
    pipeline_available = callable(getattr(backend.get("pipeline"), "analyze", None))
    enabled = bool(documents) and not extraction_errors and pipeline_available and not processing
    clicked = st.button(
        "Analyze documents",
        type="primary",
        disabled=not enabled,
        key=f"analyze_{client_id}",
    )
    if not documents:
        st.caption("Select at least one document to enable analysis.")
    elif not pipeline_available:
        st.caption("Analysis is unavailable until core.pipeline.analyze(client_id, documents) is connected.")
    elif extraction_errors:
        st.caption("Resolve document extraction errors before analysis.")
    elif processing:
        st.caption("Analysis is already in progress.")
    return clicked
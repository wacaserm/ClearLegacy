import streamlit as st

from services import gui_adapter


def _render_citations(citations, names):
    for item in citations:
        if item.get("sourceType") == "document":
            source = item.get("filename") or names.get(item.get("sourceId")) or item.get("sourceId", "Document")
            st.caption(f"📄 {source} · {item.get('location', '')}: \"{item.get('quote', '')}\"")
        else:
            st.caption(f"🏦 {item.get('sourceId', 'Account')} · {item.get('field', '')}: {item.get('value', '')}")


def render_assistant(client_id, client, accounts, analysis, workspace, source):
    """Read-only Q&A about the current live analysis. Calls Bedrock only when a question is submitted."""
    if analysis is None:
        st.info("Run an analysis first, then ask questions about this household's documents and accounts.")
        return
    if source != "live":
        st.info("Questions are available for live analyses only, not fixture samples.")
        return

    st.caption(
        "Answers use only this analysis and the supplied account records, and every answer cites its sources. "
        "Read-only: nothing is changed or sent. Not legal advice."
    )
    names = analysis.get("sourceNames") or {}
    chats = workspace.setdefault("chat", {})
    history = chats.setdefault(analysis.get("analysisId") or "current", [])

    for turn in history:
        st.chat_message("user").write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            _render_citations(turn.get("citations", []), names)

    question = st.chat_input("Ask about this household, e.g. Which accounts have a beneficiary mismatch?",
                             key=f"ask_{client_id}")
    if not question:
        return
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Checking the documents and records…"):
                reply = gui_adapter.ask_question(question, client, accounts, analysis, history)
        except Exception as error:
            st.error(f"The question could not be answered: {error}")
            return
        st.write(reply["answer"])
        _render_citations(reply.get("citations", []), names)
    history.append({"question": question, "answer": reply["answer"], "citations": reply.get("citations", [])})

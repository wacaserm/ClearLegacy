import streamlit as st

from services import gui_adapter
from ui import compat
from ui.html import esc, render

LOGO = "ui/assets/clear-legacy-logo.png"

STARTERS = {
    "review_needed": [
        "Which findings matter most, and why?",
        "Who is named as beneficiary on each account?",
        "What should I confirm with the client first?",
    ],
    "no_discrepancies_found": [
        "Do the account beneficiaries match the stated wishes?",
        "Who is named on each account?",
        "When were the designations last updated?",
    ],
    "needs_information": [
        "What information is missing for this review?",
        "What should I request from the client?",
        "How current are the account records?",
    ],
}


def _citations_html(citations, names):
    rows = []
    for item in citations:
        if item.get("sourceType") == "document":
            source = item.get("filename") or names.get(item.get("sourceId")) or item.get("sourceId", "Document")
            rows.append(f'<blockquote class="cl-quote">{esc(item.get("quote", ""))}</blockquote>'
                        f'<p class="cl-source">{esc(source)} · {esc(item.get("location", ""))}</p>')
        else:
            rows.append(f'<p class="cl-source"><b>{esc(item.get("sourceId", "Account"))}</b> · '
                        f'{esc(item.get("field", ""))}: {esc(item.get("value", ""))}</p>')
    return "".join(rows)


def _render_answer(answer, citations, names):
    st.markdown(answer.replace("$", "\\$"))
    if citations:
        with st.expander(f"Sources ({len(citations)})"):
            render(_citations_html(citations, names))


def render_assistant(client_id, client, accounts, analysis, workspace, source):
    """Read-only Q&A about the current live analysis. Calls Bedrock only when a question is submitted."""
    if analysis is None:
        render('<div class="cl-card quiet"><p class="cl-section">Ask about this household</p>'
               '<p class="cl-muted">Run an analysis first. Then ask follow-up questions; every answer cites the '
               "documents and account records it is based on.</p></div>")
        return
    if source != "live":
        render('<div class="cl-notice sample">Questions are available for live analyses only, not sample results.</div>')
        return

    render('<p class="cl-small" style="margin:0 0 12px">Answers use only this analysis and the supplied account records, '
           "and cite their sources. Read-only: nothing is changed or sent. Not legal advice.</p>")
    names = analysis.get("sourceNames") or {}
    chats = workspace.setdefault("chat", {})
    history = chats.setdefault(analysis.get("analysisId") or "current", [])

    question = None
    if not history:
        starters = STARTERS.get(analysis.get("status"), STARTERS["review_needed"])
        columns = st.columns(len(starters))
        for i, (column, starter) in enumerate(zip(columns, starters)):
            with column:
                if compat.button(starter, key=f"chip_{client_id}_{i}", stretch=True):
                    question = starter

    for turn in history:
        st.chat_message("user").write(turn["question"])
        with st.chat_message("assistant", avatar=LOGO):
            _render_answer(turn["answer"], turn.get("citations", []), names)

    typed = st.chat_input("Ask about this household", key=f"ask_{client_id}")
    question = typed or question
    if not question:
        return
    st.chat_message("user").write(question)
    with st.chat_message("assistant", avatar=LOGO):
        try:
            with st.spinner("Checking the documents and records…"):
                reply = gui_adapter.ask_question(question, client, accounts, analysis, history)
        except Exception as error:
            render(f'<div class="cl-notice error">The question could not be answered: {esc(error)}</div>')
            return
        _render_answer(reply["answer"], reply.get("citations", []), names)
    history.append({"question": question, "answer": reply["answer"], "citations": reply.get("citations", [])})
    if not typed:
        st.rerun()  # hide the starter chips once a conversation has begun

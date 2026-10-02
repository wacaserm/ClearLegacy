import time

import streamlit as st

from services import gui_adapter
from ui.empty_states import render_analysis_state
from ui.assistant import render_assistant
from ui.findings import render_findings
from ui.household import render_account_details, render_household
from ui.review import render_history
from ui.sidebar import render_sidebar
from ui.state import (
    begin_analysis,
    complete_analysis,
    fail_analysis,
    fingerprint_documents,
    get_current_analysis,
    get_workspace,
    initialize_state,
    load_sample_analysis,
    pop_notice,
    save_decision,
    select_household,
    set_notice,
    sync_uploads,
)
from ui.theme import apply_theme
from ui.uploads import render_analyze_button, render_uploads
from ui.aws_status import render_aws_warnings
from ui.html import esc, render


st.set_page_config(
    page_title="ClearLegacy · Advisor Review",
    page_icon="ui/assets/clear-legacy-logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()

STEP_LABELS = {
    "reading": "Reading documents",
    "ocr": "Running OCR on scanned pages",
    "extracting": "Extracting facts",
    "checking": "Checking quotes against the documents",
    "comparing": "Comparing to account records",
    "explaining": "Writing explanations",
    "summary": "Writing the case summary",
}


def _steps_html(done, current, detail):
    items = [f'<li class="done">✓ {esc(STEP_LABELS[step])}</li>' for step in done if step != current]
    if current:
        items.append(f'<li class="now">{esc(STEP_LABELS[current])}'
                     + (f' <span class="cl-small">· {esc(detail)}</span>' if detail else "") + "</li>")
    return '<ul class="cl-steps">' + "".join(items) + "</ul>"

backend = gui_adapter.backend_status()
try:
    households = gui_adapter.get_households(backend)
except Exception as error:
    households = gui_adapter._fixture_households()
    st.session_state["clearlegacy_household_warning"] = str(error)

if not households:
    render('<div class="cl-title" role="heading" aria-level="1">ClearLegacy</div>'
           '<div class="cl-notice">No client records or fictional household fixtures are available in this checkout.</div>')
    st.stop()

household_ids = [item["clientId"] for item in households]
state = initialize_state(household_ids)
selected_client_id = render_sidebar(
    households,
    state["selected_client_id"],
    backend,
    {cid: workspace["status"] for cid, workspace in state["workspaces"].items()},
)
if selected_client_id is None:
    st.stop()
select_household(selected_client_id)
workspace = get_workspace(selected_client_id)

load_messages = []
try:
    client = gui_adapter.get_client(selected_client_id, backend)
except Exception as error:
    client = {"clientId": selected_client_id, "name": next(
        item["name"] for item in households if item["clientId"] == selected_client_id
    )}
    load_messages.append(f"Client profile could not be loaded: {error}")
try:
    accounts = gui_adapter.get_accounts(selected_client_id, backend)
except Exception as error:
    accounts = []
    load_messages.append(f"Account records could not be loaded: {error}")

header_slot = st.empty()
messages_slot = st.empty()
render_account_details(accounts)
render('<div style="height:24px"></div>')
documents, previews, extraction_errors, documents_card = render_uploads(selected_client_id, backend)
upload_fingerprint = fingerprint_documents(documents)
had_analysis = bool(workspace["current_analysis_id"])
uploads_changed = sync_uploads(selected_client_id, upload_fingerprint)
if uploads_changed and had_analysis:
    st.rerun()

workspace = get_workspace(selected_client_id)
with header_slot.container():
    render_household(client, workspace["status"], accounts)
# Messages go into one fixed container: a varying number of elements above st.tabs
# would change the tabs' position, and Streamlit would reset them to the first tab.
with messages_slot.container():
    if st.session_state.pop("clearlegacy_household_warning", None):
        render('<div class="cl-notice warn">Stored client records are unavailable; using fictional fixture households.</div>')
    for message in load_messages:
        render(f'<div class="cl-notice warn">{esc(message)}</div>')
    render_aws_warnings()
    notice = pop_notice(selected_client_id)
    if notice:
        tone = "error" if notice.startswith("Error:") else "ok"
        render(f'<div class="cl-notice {tone}">{esc(notice.removeprefix("Error: "))}</div>')

with documents_card:
    analyze_clicked = render_analyze_button(
        selected_client_id,
        documents,
        extraction_errors,
        backend,
        workspace["processing"],
    )
    progress_box = st.empty()
if analyze_clicked:
    begin_analysis(selected_client_id)
    started = time.monotonic()
    try:
        with progress_box.container(), st.status("Analyzing documents…", expanded=True) as status_box:
            steps_slot = st.empty()
            done_steps = []

            def on_progress(step, detail=None):
                if step not in STEP_LABELS:
                    return
                if step not in done_steps:
                    done_steps.append(step)
                steps_slot.markdown(_steps_html(done_steps, step, detail), unsafe_allow_html=True)

            result = gui_adapter.analyze_documents(selected_client_id, documents, backend, previews, progress=on_progress)
            if isinstance(result, dict) and result.get("findings"):
                on_progress("summary")
                result["summary"] = gui_adapter.summarize(client, result["findings"], result)
            status_box.update(label="Analysis complete", state="complete", expanded=False)
        if not isinstance(result, dict):
            raise ValueError("The analysis pipeline returned an unsupported response.")
        allowed_statuses = {
            "review_needed",
            "no_discrepancies_found",
            "needs_information",
            "failed",
        }
        if result.get("status") not in allowed_statuses:
            raise ValueError("The analysis pipeline returned an unknown status.")
        if result["status"] == "failed":
            fail_analysis(
                selected_client_id,
                result.get("message", "The analysis pipeline reported a failure."),
            )
        elif not isinstance(result.get("findings", []), list):
            raise ValueError("The analysis pipeline returned malformed findings.")
        else:
            result.setdefault("findings", [])
            result.setdefault("clarificationQuestions", [])
            result.setdefault("warnings", [])
            result.setdefault("analysisId", None)
            result["elapsedSeconds"] = time.monotonic() - started
            complete_analysis(
                selected_client_id,
                result,
                "live",
                upload_fingerprint,
            )
    except Exception as error:
        fail_analysis(selected_client_id, f"Analysis failed: {error}")
    st.rerun()

render('<div style="height:16px"></div>')
findings_tab, ask_tab, history_tab = st.tabs(["Findings", "Ask ClearLegacy", "Review history"])
review_event = None
with findings_tab:
    current_analysis = get_current_analysis(selected_client_id)
    if current_analysis is None:
        load_sample = render_analysis_state(
            workspace["status"],
            workspace["error"],
            selected_client_id,
            sample_available=not callable(getattr(backend.get("pipeline"), "analyze", None)),
        )
        if load_sample:
            try:
                sample_result = gui_adapter.sample_analysis(selected_client_id)
                load_sample_analysis(selected_client_id, sample_result)
                st.rerun()
            except Exception as error:
                render(f'<div class="cl-notice error">Sample results could not be loaded: {esc(error)}</div>')
    else:
        source = workspace["analyses"][workspace["current_analysis_id"]]["source"]
        review_event = render_findings(
            selected_client_id,
            current_analysis,
            workspace,
            sample=source == "sample",
        )

with ask_tab:
    current_analysis = get_current_analysis(selected_client_id)
    analysis_source = (
        workspace["analyses"][workspace["current_analysis_id"]]["source"]
        if current_analysis is not None else None
    )
    render_assistant(selected_client_id, client, accounts, current_analysis, workspace, analysis_source)

with history_tab:
    persistent_history, history_error = gui_adapter.get_audit(selected_client_id, backend)
    render_history(workspace["history"], persistent_history, history_error)

if review_event:
    if review_event["sample"]:
        persistence = {"status": "Session-only", "error": None, "timestamp": None}
    else:
        persistence = gui_adapter.persist_decision(
            selected_client_id,
            review_event["analysis_id"],
            review_event["finding_id"],
            review_event["decision"],
            review_event["reviewer"],
            review_event["note"],
            backend,
        )
    save_decision(
        selected_client_id,
        review_event["analysis_id"],
        review_event["finding_id"],
        review_event["decision"],
        review_event["note"],
        review_event["reviewer"],
        persistence,
    )
    if persistence["error"]:
        set_notice(selected_client_id, f"Error: Decision is session-only; persistent save failed: {persistence['error']}")
    elif review_event["sample"]:
        set_notice(selected_client_id, "Sample review decision saved for this session only.")
    elif persistence["status"] == "Persistently saved":
        set_notice(selected_client_id, "Decision and note persistently saved.")
    else:
        set_notice(selected_client_id, "Decision and note saved for this session only.")
    if review_event["decision"] == "attorney_review":
        set_notice(
            selected_client_id,
            f"{workspace['notice']} Attorney review is an internal flag; nothing is sent externally.",
        )
    st.rerun()

render('<p class="cl-small" style="margin-top:32px">Findings support advisor review and are not legal advice. '
       "Attorney review is an internal flag; nothing is sent externally.</p>")
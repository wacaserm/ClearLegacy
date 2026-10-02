import streamlit as st

from services import gui_adapter
from ui.empty_states import render_analysis_state
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


st.set_page_config(page_title="ClearLegacy | Advisor Review", layout="wide")
apply_theme()

backend = gui_adapter.backend_status()
try:
    households = gui_adapter.get_households(backend)
except Exception as error:
    households = []
    st.error(f"Household records could not be loaded: {error}")

if not households:
    st.title("ClearLegacy")
    st.info("No client records or fictional household fixtures are available in this checkout.")
    st.caption("The store contract is core.store.get_clients().")
    st.stop()

household_ids = [item["clientId"] for item in households]
state = initialize_state(household_ids)
selected_client_id = render_sidebar(
    households,
    state["selected_client_id"],
    backend,
)
if selected_client_id is None:
    st.stop()
select_household(selected_client_id)
workspace = get_workspace(selected_client_id)

try:
    client = gui_adapter.get_client(selected_client_id, backend)
except Exception as error:
    client = {"clientId": selected_client_id, "name": next(
        item["name"] for item in households if item["clientId"] == selected_client_id
    )}
    st.warning(f"Client profile could not be loaded: {error}")
try:
    accounts = gui_adapter.get_accounts(selected_client_id, backend)
except Exception as error:
    accounts = []
    st.warning(f"Account records could not be loaded: {error}")

header_slot = st.empty()
st.subheader("Documents")
documents, previews, extraction_errors = render_uploads(selected_client_id, backend)
upload_fingerprint = fingerprint_documents(documents)
had_analysis = bool(workspace["current_analysis_id"])
uploads_changed = sync_uploads(selected_client_id, upload_fingerprint)
if uploads_changed and had_analysis:
    st.rerun()

workspace = get_workspace(selected_client_id)
with header_slot.container():
    render_household(client, workspace["status"])
notice = pop_notice(selected_client_id)
if notice:
    if notice.startswith("Error:"):
        st.error(notice)
    else:
        st.success(notice)

analyze_clicked = render_analyze_button(
    selected_client_id,
    documents,
    extraction_errors,
    backend,
    workspace["processing"],
)
if analyze_clicked:
    begin_analysis(selected_client_id)
    try:
        with st.spinner("Running the configured ClearLegacy analysis pipeline…"):
            result = gui_adapter.analyze_documents(selected_client_id, documents, backend)
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
            complete_analysis(
                selected_client_id,
                result,
                "live",
                upload_fingerprint,
            )
    except Exception as error:
        fail_analysis(selected_client_id, f"Analysis failed: {error}")
    st.rerun()

render_account_details(accounts)

findings_tab, history_tab = st.tabs(["Findings", "Review history"])
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
                st.error(f"Fixture sample could not be loaded: {error}")
    else:
        source = workspace["analyses"][workspace["current_analysis_id"]]["source"]
        review_event = render_findings(
            selected_client_id,
            current_analysis,
            workspace,
            sample=source == "sample",
        )

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

st.caption("Findings support advisor review and are not legal advice.")
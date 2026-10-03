import hashlib
import uuid
from datetime import datetime

import streamlit as st


STATE_KEY = "clearlegacy_ui"
CURRENT_ANALYSIS_STATUSES = {
    "review_needed",
    "no_discrepancies_found",
    "needs_information",
    "client_mismatch",
}


def initialize_state(household_ids):
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = {
            "selected_client_id": household_ids[0] if household_ids else None,
            "workspaces": {},
        }
    state = st.session_state[STATE_KEY]
    if state.get("selected_client_id") not in household_ids:
        state["selected_client_id"] = household_ids[0] if household_ids else None
    for client_id in household_ids:
        state["workspaces"].setdefault(
            client_id,
            {
                "upload_fingerprint": None,
                "status": "not_analyzed",
                "current_analysis_id": None,
                "analyses": {},
                "decisions": {},
                "history": [],
                "notice": None,
                "error": None,
                "processing": False,
            },
        )
    return state


def select_household(client_id):
    st.session_state[STATE_KEY]["selected_client_id"] = client_id


def get_workspace(client_id):
    return st.session_state[STATE_KEY]["workspaces"][client_id]


def get_current_analysis(client_id):
    workspace = get_workspace(client_id)
    if workspace["status"] not in CURRENT_ANALYSIS_STATUSES:
        return None
    analysis_id = workspace["current_analysis_id"]
    if not analysis_id:
        return None
    return workspace["analyses"].get(analysis_id, {}).get("result")


def fingerprint_documents(documents):
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: (item["category"], item["filename"])):
        content = document["file_bytes"]
        digest.update(document["category"].encode("utf-8"))
        digest.update(document["filename"].encode("utf-8"))
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def sync_uploads(client_id, fingerprint):
    workspace = get_workspace(client_id)
    previous = workspace["upload_fingerprint"]
    if previous == fingerprint:
        return False
    workspace["upload_fingerprint"] = fingerprint
    if workspace["current_analysis_id"]:
        current = workspace["analyses"].get(workspace["current_analysis_id"])
        if current is not None:
            current["outdated"] = True
        workspace["status"] = "outdated"
        workspace["error"] = None
        workspace["notice"] = "Selected files changed. Run analysis again before using earlier findings."
    return True


def begin_analysis(client_id):
    workspace = get_workspace(client_id)
    workspace.update(status="processing", processing=True, error=None, notice=None)


def complete_analysis(client_id, result, source, fingerprint):
    workspace = get_workspace(client_id)
    analysis_id = result.get("analysisId") or str(uuid.uuid4())
    normalized = dict(result)
    normalized["analysisId"] = analysis_id
    workspace["analyses"][analysis_id] = {
        "result": normalized,
        "source": source,
        "upload_fingerprint": fingerprint,
        "outdated": False,
    }
    workspace.update(
        status=normalized["status"],
        processing=False,
        current_analysis_id=analysis_id,
        error=None,
        notice=None,
    )
    return analysis_id


def fail_analysis(client_id, message):
    workspace = get_workspace(client_id)
    workspace.update(
        status="failed",
        processing=False,
        current_analysis_id=None,
        error=message,
        notice=None,
    )


def load_sample_analysis(client_id, result):
    workspace = get_workspace(client_id)
    fingerprint = workspace["upload_fingerprint"]
    return complete_analysis(client_id, result, "sample", fingerprint)


def save_decision(client_id, analysis_id, finding_id, decision, note, reviewer, persistence):
    workspace = get_workspace(client_id)
    key = f"{analysis_id}:{finding_id}"
    record = {
        "analysisId": analysis_id,
        "findingId": finding_id,
        "decision": decision,
        "note": note,
        "reviewer": reviewer,
        "timestamp": persistence.get("timestamp") or datetime.now().astimezone().isoformat(timespec="minutes"),
        "persistence": persistence.get("status", "Session-only"),
        "error": persistence.get("error"),
    }
    workspace["decisions"][key] = record
    workspace["history"].insert(0, record)
    return record


def record_event(client_id, analysis_id, event, note, reviewer, persistence):
    """Add a system event (not a finding decision) to the household's session history."""
    record = {
        "analysisId": analysis_id,
        "findingId": "client-check",
        "decision": event,
        "note": note,
        "reviewer": reviewer,
        "timestamp": datetime.now().astimezone().isoformat(timespec="minutes"),
        "persistence": persistence.get("status", "Session-only"),
        "error": persistence.get("error"),
    }
    get_workspace(client_id)["history"].insert(0, record)
    return record


def upload_key(client_id):
    """Widget key for the household's uploader; bumping the round clears the selected files."""
    round_ = st.session_state.get(f"clearlegacy_upload_round_{client_id}", 0)
    return f"planning_uploads_{client_id}" + (f"_{round_}" if round_ else "")


def clear_uploads(client_id):
    """Drop this household's selected files and the stopped analysis (history is kept)."""
    round_key = f"clearlegacy_upload_round_{client_id}"
    st.session_state.pop(upload_key(client_id), None)
    st.session_state[round_key] = st.session_state.get(round_key, 0) + 1
    workspace = get_workspace(client_id)
    workspace.update(status="not_analyzed", current_analysis_id=None, upload_fingerprint=fingerprint_documents([]),
                     processing=False, error=None, notice=None)


def set_notice(client_id, message):
    get_workspace(client_id)["notice"] = message


def pop_notice(client_id):
    workspace = get_workspace(client_id)
    notice = workspace["notice"]
    workspace["notice"] = None
    return notice
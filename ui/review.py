import streamlit as st


DECISIONS = (
    ("Needs follow-up", "needs_follow_up"),
    ("Dismiss", "dismissed"),
    ("Flag for attorney review", "attorney_review"),
)


def render_finding_actions(client_id, analysis_id, finding_id, existing_decision, sample):
    key = f"{client_id}:{analysis_id}:{finding_id}"
    if existing_decision:
        st.caption(f"Current decision: {existing_decision.replace('_', ' ').title()}")
    if sample:
        st.caption("Fixture example only · decisions are not persisted to the backend.")
    note = st.text_area(
        "Advisor note",
        key=f"review_note_{key}",
        placeholder="Add the agreed follow-up or reason for dismissal.",
    )
    reviewer = st.text_input(
        "Reviewer (optional)",
        key=f"reviewer_{key}",
        placeholder="Name",
    )
    event = None
    action_columns = st.columns(3)
    for column, (label, decision) in zip(action_columns, DECISIONS):
        with column:
            if st.button(label, key=f"action_{decision}_{key}"):
                event = {
                    "analysis_id": analysis_id,
                    "finding_id": finding_id,
                    "decision": decision,
                    "note": note.strip(),
                    "reviewer": reviewer.strip() or "Not provided",
                    "sample": sample,
                }
    return event


def _audit_row(record, persistence):
    status = record.get("decision") or record.get("status") or "Not provided"
    return {
        "Status": str(status).replace("_", " ").title(),
        "Note": record.get("note") or "No note",
        "Reviewer": record.get("reviewer") or record.get("user") or "Not provided",
        "Timestamp": record.get("timestamp") or record.get("createdAt") or "Not provided",
        "Persistence": persistence,
        "Analysis": record.get("analysisId") or record.get("analysis_id") or "Not provided",
        "Finding": record.get("findingId") or record.get("finding_id") or "Not provided",
    }


def render_history(local_history, persistent_history, persistence_error=None):
    if persistence_error:
        st.warning(f"Persistent history could not be loaded: {persistence_error}")
    rows = []
    persisted_keys = set()
    for record in persistent_history:
        if not isinstance(record, dict):
            continue
        row = _audit_row(record, "Persistently saved")
        rows.append(row)
        persisted_keys.add((row["Analysis"], row["Finding"], row["Status"].lower()))
    for record in local_history:
        identity = (
            record.get("analysisId", "Not provided"),
            record.get("findingId", "Not provided"),
            str(record.get("decision", "Not provided")).replace("_", " ").lower(),
        )
        if identity in persisted_keys:
            continue
        rows.append(_audit_row(record, record.get("persistence", "Session-only")))
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("No review decisions are available for this household yet.")
    st.caption("Session-only decisions last for this Streamlit session. Persistent status is shown only after the store confirms a write.")
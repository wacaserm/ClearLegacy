import streamlit as st

from core import config
from ui import compat
from ui.html import esc, quote_text, render

DECISIONS = (
    ("Confirm", "confirmed"),
    ("Dismiss", "dismissed"),
    ("Flag for attorney", "attorney_review"),
)

DECISION_LABELS = {
    "confirmed": ("Confirmed", "clear"),
    "dismissed": ("Dismissed", "neutral"),
    "attorney_review": ("Flagged for attorney review", "review"),
    "needs_follow_up": ("Needs follow-up", "high"),  # decisions recorded before the redesign
    "analysis_stopped": ("Analysis stopped", "critical"),  # wrong-client safety check
    "confirm": ("Confirmed", "clear"),
    "dismiss": ("Dismissed", "neutral"),
}


def decision_label(decision):
    return DECISION_LABELS.get(decision, (str(decision or "Not provided").replace("_", " ").capitalize(), "neutral"))


REVIEWER_KEY = "clearlegacy_reviewer"
MIN_DISMISS_WORDS = 3


def current_reviewer() -> str:
    return " ".join(str(st.session_state.get(REVIEWER_KEY, "")).split())


def valid_reviewer(name) -> bool:
    return len("".join(str(name or "").split())) >= 2


def render_reviewer_field():
    """One reviewer name for the session; required for every decision."""
    st.text_input("Reviewer", key=REVIEWER_KEY, placeholder="Your name",
                  help="Required. Your name is recorded with every decision in the review history.")


def render_finding_actions(client_id, analysis_id, finding_id, existing_decision, sample):
    key = f"{client_id}:{analysis_id}:{finding_id}"
    reviewer = current_reviewer()
    if sample:
        render('<p class="cl-small">Sample result · decisions are kept for this session only.</p>')
    note = st.text_area(
        "Note", key=f"review_note_{key}", height=68,
        placeholder="Optional for Confirm and Flag. For Dismiss: why isn't this an issue? "
                    "e.g. 'Account intended for different heirs'",
    )
    ready = valid_reviewer(reviewer)
    event, error = None, None
    columns = st.columns([1, 1, 1.6, 1.2])
    for column, (label, decision) in zip(columns, DECISIONS):
        with column:
            if compat.button(label, key=f"action_{decision}_{key}", stretch=True, disabled=not ready,
                             type="primary" if decision == "confirmed" else "secondary"):
                if decision == "dismissed" and len(note.split()) < MIN_DISMISS_WORDS:
                    error = "Add a short reason before dismissing, e.g. 'Account intended for different heirs'."
                else:
                    event = {
                        "analysis_id": analysis_id,
                        "finding_id": finding_id,
                        "decision": decision,
                        "note": note.strip(),
                        "reviewer": reviewer,
                        "sample": sample,
                    }
    if not ready:
        render('<div class="cl-notice warn" style="margin-top:4px">Enter your name to record this decision.</div>')
    if error:
        render(f'<div class="cl-notice error" style="margin-top:4px">{esc(error)}</div>')
    render('<p class="cl-small" style="margin:4px 0 0">Attorney review is an internal flag; nothing is sent externally.</p>')
    return event


def _reviewer(value):
    return "—" if not value or value == "Not provided" else value


def _audit_row(record, persistence):
    label, tone = decision_label(record.get("decision") or record.get("status"))
    return {
        "decision": label,
        "tone": tone,
        "note": record.get("note") or "",
        "reviewer": _reviewer(record.get("reviewer") or record.get("user")),
        "timestamp": record.get("timestamp") or record.get("createdAt") or "",
        "persistence": persistence,
        "analysis": record.get("analysisId") or record.get("analysis_id") or "",
        "finding": record.get("findingId") or record.get("finding_id") or "",
    }


def render_history(local_history, persistent_history, persistence_error=None):
    if persistence_error:
        render(f'<div class="cl-notice warn">Saved history could not be loaded: {esc(persistence_error)}</div>')
    rows, persisted_keys = [], set()
    for record in persistent_history:
        if not isinstance(record, dict):
            continue
        row = _audit_row(record, "Saved")
        rows.append(row)
        persisted_keys.add((row["analysis"], row["finding"], str(record.get("decision", "")).lower()))
    for record in local_history:
        identity = (record.get("analysisId", ""), record.get("findingId", ""), str(record.get("decision", "")).lower())
        if identity in persisted_keys:
            continue
        status = record.get("persistence", "Session-only")
        rows.append(_audit_row(record, "Saved" if status == "Persistently saved" else status))
    rows.sort(key=lambda r: r["timestamp"], reverse=True)

    if not rows:
        render('<div class="cl-card quiet"><p class="cl-section">No decisions yet</p>'
               '<p class="cl-muted">Decisions you record on findings appear here with their note and reviewer.</p></div>')
    else:
        body = "".join(
            "<tr>"
            f'<td class="num">{esc(r["timestamp"][:16].replace("T", " "))}</td>'
            f'<td><span class="cl-pill {esc(r["tone"])}">{esc(r["decision"])}</span></td>'
            f'<td>{quote_text(r["note"]) or "<span class=sub style=display:inline>No note</span>"}</td>'
            f'<td>{esc(r["reviewer"])}</td>'
            f'<td>{esc(r["persistence"])}<span class="sub">{esc(r["finding"][:28])}</span></td>'
            "</tr>"
            for r in rows
        )
        render('<div class="cl-table-wrap"><table class="cl-table"><thead><tr>'
               "<th>When</th><th>Decision</th><th>Note</th><th>Reviewer</th><th>Status</th>"
               "</tr></thead><tbody>" + body + "</tbody></table></div>")
    notes = []
    if config.pii_masking():
        notes.append("PII masking is on: account numbers, SSNs, phone numbers and emails in saved notes are "
                     "stored masked (for example [PHONE]), so they appear that way here.")
    notes.append("Session-only decisions last for this browser session. \"Saved\" means the store confirmed the write.")
    render('<p class="cl-small" style="margin-top:8px">' + esc(" ".join(notes)) + "</p>")

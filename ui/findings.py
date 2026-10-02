import streamlit as st

from ui import compat
from ui.review import render_finding_actions


def _render_evidence(evidence):
    document_evidence = [item for item in evidence if item.get("sourceType") == "document"]
    account_evidence = [item for item in evidence if item.get("sourceType") == "account"]
    document_column, account_column = st.columns(2)
    with document_column:
        st.markdown("**Document evidence**")
        if not document_evidence:
            st.caption("No document evidence supplied.")
        for item in document_evidence:
            st.caption(
                f"{item.get('filename', 'Document')} · "
                f"{item.get('location', 'Location not supplied')}"
            )
            st.write(item.get("quote", item.get("value", "Evidence text not supplied.")))
    with account_column:
        st.markdown("**Account evidence**")
        if not account_evidence:
            st.caption("No account evidence supplied.")
        for item in account_evidence:
            source_name = item.get("filename", "Account record")
            location = item.get("location", "Supplied account record")
            st.caption(f"{source_name} · {location}")
            if item.get("quote"):
                st.write(item["quote"])
            elif item.get("field") or item.get("value"):
                st.write(f"{item.get('field', 'Record')}: {item.get('value', 'Not provided')}")
            else:
                st.write("Account evidence value not supplied.")


def render_findings(client_id, analysis, workspace, sample=False):
    if not analysis:
        return None
    if sample:
        st.warning("Sample fixture results · these findings were not produced from your uploaded files.")
    status = analysis.get("status")
    findings = analysis.get("findings", [])
    event = None
    if status == "no_discrepancies_found":
        st.success("No discrepancies found within the supplied scope.")
    elif status == "needs_information":
        st.warning("More information is needed to complete this review.")
    elif status == "review_needed":
        st.info(f"{len(findings)} finding(s) need advisor review.")

    if analysis.get("summary"):
        with st.container(border=True):
            st.markdown("**Case summary**")
            st.write(analysis["summary"])
            st.caption("AI-generated from the findings below. Review the evidence before acting.")

    for warning in analysis.get("warnings", []):
        st.warning(warning)
    for question in analysis.get("clarificationQuestions", []):
        st.markdown(f"**Clarification question**  \n{question}")
    if not findings and not analysis.get("clarificationQuestions") and status == "review_needed":
        st.info("The analysis requested review but did not return findings.")

    analysis_id = analysis.get("analysisId", "unknown-analysis")
    for index, finding in enumerate(findings):
        finding_id = finding.get("findingId", f"finding-{index + 1}")
        with st.container(border=True):
            priority = str(finding.get("priority", "review")).replace("_", " ").title()
            color = "red" if priority.lower() in {"critical", "high"} else "orange"
            compat.badge(f"{priority} priority", color=color)
            st.subheader(finding.get("title", "Finding"))
            st.write(finding.get("explanation", "No explanation was provided."))
            follow_up = finding.get("followUpQuestion") or finding.get("clarificationQuestion")
            if follow_up:
                st.markdown(f"**Follow-up question**  \n{follow_up}")
            recommended = finding.get("recommendedAction")
            if recommended:
                st.markdown(f"**Recommended action**  \n{recommended}")
            evidence = finding.get("evidence", [])
            _render_evidence(evidence if isinstance(evidence, list) else [])
            with st.expander("Technical identifiers"):
                st.write({
                    "analysisId": analysis_id,
                    "findingId": finding_id,
                    "sourceIds": [item.get("sourceId") for item in evidence if isinstance(item, dict)],
                })
            decision_key = f"{analysis_id}:{finding_id}"
            existing = workspace["decisions"].get(decision_key)
            event = render_finding_actions(
                client_id,
                analysis_id,
                finding_id,
                existing.get("decision") if existing else None,
                sample,
            ) or event
    return event
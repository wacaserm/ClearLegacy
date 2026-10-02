import streamlit as st


def render_analysis_state(status, error, client_id, sample_available):
    if status == "failed":
        st.error(error or "Analysis failed. No findings are available for this run.")
        return False
    if status == "outdated":
        st.warning("Selected documents changed. Reanalyze before using prior results.")
        return False
    if status == "not_analyzed":
        st.info("Upload planning documents and account records, then run an analysis to review evidence.")
        if sample_available:
            return st.button(
                "Load clearly labeled fixture sample",
                key=f"load_sample_{client_id}",
            )
    elif status == "processing":
        st.info("Analysis is in progress.")
    elif status == "needs_information":
        st.warning("More information is needed. Review the questions and warnings below.")
    elif status == "no_discrepancies_found":
        st.success("No discrepancies found within the supplied scope.")
    elif status == "review_needed":
        st.info("Review the findings and record a follow-up decision.")
    return False
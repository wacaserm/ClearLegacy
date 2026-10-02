import streamlit as st


STATUS_LABELS = {
    "not_analyzed": ("Not analyzed", "gray"),
    "processing": ("Processing", "blue"),
    "review_needed": ("Review needed", "orange"),
    "needs_information": ("Insufficient information", "orange"),
    "no_discrepancies_found": ("No discrepancies found · supplied scope", "green"),
    "failed": ("Analysis failed", "red"),
    "outdated": ("Results outdated · reanalyze", "orange"),
}


def render_household(client, status):
    name = client.get("name") or client.get("clientName") or "Household"
    title, badge = st.columns([4, 1], vertical_alignment="center")
    with title:
        st.title(name)
    with badge:
        label, color = STATUS_LABELS.get(status, ("Not analyzed", "gray"))
        st.markdown(f":{color}[**{label}**]")


def render_account_details(accounts):
    with st.expander("Account details", expanded=False):
        if accounts:
            st.dataframe(accounts, hide_index=True, width="stretch")
        else:
            st.info(
                "No account summary is available from the configured store. "
                "Account details are not inferred from document filenames."
            )
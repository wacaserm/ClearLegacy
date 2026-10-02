import streamlit as st

from ui import compat


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

    st.title(name)
    label, color = STATUS_LABELS.get(status, ("Not analyzed", "gray"))
    st.badge(label, color=color)


def render_account_details(accounts):
    with st.expander("Account details", expanded=False):
        if accounts:
            compat.dataframe(accounts)
        else:
            st.info(
                "No account summary is available from the configured store. "
                "Account details are not inferred from document filenames."
            )
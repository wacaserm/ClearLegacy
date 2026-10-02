import streamlit as st


def render_sidebar(households, selected_client_id, backend):
    with st.sidebar:
        st.markdown("### ClearLegacy")
        st.caption("Advisor review workspace")
        if not households:
            st.info("No fictional households or stored clients are available.")
            return None
        ids = [household["clientId"] for household in households]
        selected = st.selectbox(
            "Household",
            ids,
            index=ids.index(selected_client_id) if selected_client_id in ids else 0,
            format_func=lambda client_id: next(
                item["name"] for item in households if item["clientId"] == client_id
            ),
            key="clearlegacy_household_picker",
        )
        missing = [
            label
            for key, label in (
                ("reader", "document reader"),
                ("pipeline", "analysis pipeline"),
                ("store", "persistent store"),
            )
            if not backend.get(key)
        ]
        if missing:
            st.caption("Not connected: " + ", ".join(missing))
        return selected
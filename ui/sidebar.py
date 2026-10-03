import streamlit as st

from ui import compat
from ui.aws_status import render_sidebar_footer
from ui.html import STATUS_PILLS, esc, render
from ui.state import select_household

# Streamlit's named colors for the dot in button labels; the status text always follows.
_DOT = {"neutral": "gray", "brand": "blue", "high": "orange", "review": "blue", "clear": "green", "critical": "red"}


def _account_count(household):
    record = household.get("record") or {}
    accounts = record.get("accounts") if isinstance(record, dict) else None
    return len(accounts) if isinstance(accounts, list) else None


def render_sidebar(households, selected_client_id, backend, statuses=None):
    statuses = statuses or {}
    with st.sidebar:
        logo, name = st.columns([1, 4], gap="small", vertical_alignment="center")
        with logo:
            st.image("ui/assets/clear-legacy-logo.png", width=36)
        with name:
            render('<div class="cl-brand-name">ClearLegacy</div><div class="cl-small">Advisor review workspace</div>')

        if not households:
            st.info("No fictional households or stored clients are available.")
            return None

        render('<p class="cl-label" style="margin-top:24px">Households</p>')
        ids = [household["clientId"] for household in households]
        selected = selected_client_id if selected_client_id in ids else ids[0]
        for household in households:
            client_id = household["clientId"]
            label, tone = STATUS_PILLS.get(statuses.get(client_id, "not_analyzed"), STATUS_PILLS["not_analyzed"])
            count = _account_count(household)
            accounts = f" · {count} account{'s' if count != 1 else ''}" if count is not None else ""
            text = f"**{household['name']}**\n:{_DOT.get(tone, 'gray')}[●] {label}{accounts}"
            key = f"hhactive_{client_id}" if client_id == selected else f"hh_{client_id}"
            if compat.button(text, key=key, stretch=True) and client_id != selected:
                select_household(client_id)
                st.rerun()

        missing = [
            label
            for key, label in (("reader", "document reader"), ("pipeline", "analysis pipeline"), ("store", "persistent store"))
            if not backend.get(key)
        ]
        render('<div class="cl-sidebar-foot"></div>')
        if missing:
            render(f'<p class="cl-small">Not connected: {esc(", ".join(missing))}</p>')
        render_sidebar_footer()
        render('<p class="cl-small" style="margin-top:8px">Findings support advisor review and are not legal advice.</p>')
        return selected

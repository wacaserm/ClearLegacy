"""Fallbacks for Streamlit features that older installs don't have."""

import streamlit as st


def badge(label, color="gray"):
    """st.badge where available (Streamlit 1.46+), otherwise colored bold text."""
    if hasattr(st, "badge"):
        st.badge(label, color=color)
    else:
        st.markdown(f":{color}[**{label}**]")


def dataframe(data):
    """Full-width table without the index, on old and new Streamlit versions."""
    try:
        st.dataframe(data, hide_index=True, width="stretch")
    except Exception:
        st.dataframe(data, hide_index=True, use_container_width=True)

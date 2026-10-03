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


def button(label, key, stretch=False, **kwargs):
    """st.button with full width on old and new Streamlit versions."""
    if stretch:
        try:
            return st.button(label, key=key, width="stretch", **kwargs)
        except TypeError:
            return st.button(label, key=key, use_container_width=True, **kwargs)
    return st.button(label, key=key, **kwargs)


def download_button(label, data, file_name, mime, key, stretch=False, **kwargs):
    """st.download_button with full width on old and new Streamlit versions."""
    if stretch:
        try:
            return st.download_button(label, data=data, file_name=file_name, mime=mime, key=key, width="stretch", **kwargs)
        except TypeError:
            return st.download_button(label, data=data, file_name=file_name, mime=mime, key=key,
                                      use_container_width=True, **kwargs)
    return st.download_button(label, data=data, file_name=file_name, mime=mime, key=key, **kwargs)

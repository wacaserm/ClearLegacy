import streamlit as st


def apply_theme():
    st.markdown(
        """
        <style>
        h1 { font-size: 2rem; }
        h2, h3 { font-size: 1.375rem; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 11px;
        }
        [data-testid="stSidebar"] {
            background: #F2F5F8;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
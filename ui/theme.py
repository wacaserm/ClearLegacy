import streamlit as st


def apply_theme():
    st.markdown(
        """
        <style>
        :root {
        --muted-text: #526273;
        --button-color: #1F6B63;
        --button-hover: #18564F;
        }

        h1 { font-size: 2rem; }
        h2, h3 { font-size: 1.375rem; }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 11px;
        }
        
        [data-testid="stSidebar"] {
            background: #F2F5F8;
        }

        [data-testid="stCaptionContainer"] {
            color: var(--muted-text);
        }

        .stButton > button {
            background-color: var(--button-color);
            color: white;
            border-color: var(--button-color);
        }

        .stButton > button:hover {
            background-color: var(--button-hover);
            border-color: var(--button-hover);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
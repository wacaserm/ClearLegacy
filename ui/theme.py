"""All ClearLegacy styling: design tokens as CSS variables, plus component classes.

Selectors target data-testid attributes, Streamlit's st-key-* classes (from keyed
containers/widgets), and our own cl-* classes, never generated class names.
"""

import streamlit as st

PRIORITY_COLORS = {
    "critical": "#B42318",
    "high": "#B54708",
    "review": "#175CD3",
    "clear": "#067647",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

:root {
  --brand: #00205B;
  --brand-hover: #0A2E75;
  --text: #0B1220;
  --text-2: #475467;
  --text-3: #667085;
  --line: #E4E7EC;
  --surface: #F8F9FB;
  --bg: #FFFFFF;
  --critical: #B42318; --critical-bg: #FEF3F2;
  --high: #B54708;     --high-bg: #FFFAEB;
  --review: #175CD3;   --review-bg: #EFF8FF;
  --clear: #067647;    --clear-bg: #ECFDF3;
  --neutral-bg: #F2F4F7;
  --radius: 10px;
  --radius-sm: 6px;
  --font: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

/* ---- Base ---------------------------------------------------------------- */
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
button, input, textarea, select { font-family: var(--font); }
[data-testid="stAppViewContainer"] { background: var(--bg); color: var(--text); }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { font-size: 14px; line-height: 1.55; }
h1, h2, h3, h4 { font-family: var(--font); color: var(--text); letter-spacing: -0.01em; }
.cl-num, .cl-table td.num { font-variant-numeric: tabular-nums; }

/* ---- Hide Streamlit chrome ------------------------------------------------ */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stMainMenu"], [data-testid="stAppDeployButton"], .stDeployButton,
footer, #MainMenu { display: none !important; visibility: hidden !important; }

/* ---- Layout --------------------------------------------------------------- */
[data-testid="stMainBlockContainer"], .block-container {
  max-width: 1200px; padding-top: 32px; padding-bottom: 48px; margin: 0 auto;
}
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 8px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: var(--radius); border-color: var(--line); }

/* ---- Text helpers --------------------------------------------------------- */
.cl-label {
  font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-2); margin: 0 0 8px 0;
}
.cl-title { font-size: 24px; font-weight: 600; color: var(--text); margin: 0; line-height: 1.3; }
.cl-section { font-size: 16px; font-weight: 600; color: var(--text); margin: 0 0 8px 0; }
.cl-muted { color: var(--text-2); font-size: 14px; }
.cl-small { color: var(--text-2); font-size: 12px; }
.cl-meta { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 8px; color: var(--text-2); font-size: 14px; }
.cl-meta b { color: var(--text); font-weight: 500; }

/* ---- Pills ---------------------------------------------------------------- */
.cl-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 500; line-height: 20px; white-space: nowrap;
  border: 1px solid transparent;
}
.cl-pill::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.cl-pill.plain::before { display: none; }
.cl-pill.critical { color: var(--critical); background: var(--critical-bg); }
.cl-pill.high     { color: var(--high); background: var(--high-bg); }
.cl-pill.review   { color: var(--review); background: var(--review-bg); }
.cl-pill.clear    { color: var(--clear); background: var(--clear-bg); }
.cl-pill.neutral  { color: var(--text-2); background: var(--neutral-bg); }
.cl-pill.brand    { color: var(--brand); background: #EEF2F8; }
.cl-tag {
  display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.04em; color: var(--text-2); border: 1px solid var(--line); background: var(--bg);
}

/* ---- Buttons -------------------------------------------------------------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: var(--radius-sm); font-weight: 500; font-size: 14px;
  border: 1px solid var(--line); color: var(--text); background: var(--bg);
}
.stButton > button:hover { border-color: #C9CED6; color: var(--text); background: var(--surface); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--brand); border-color: var(--brand); color: #FFFFFF;
}
.stButton > button[kind="primary"]:hover { background: var(--brand-hover); border-color: var(--brand-hover); color: #FFFFFF; }
.stButton > button:disabled { opacity: 0.45; }
button:focus-visible, input:focus-visible, textarea:focus-visible, [role="tab"]:focus-visible,
[role="checkbox"]:focus-visible, a:focus-visible {
  outline: 2px solid var(--brand) !important; outline-offset: 2px !important;
}

/* ---- Tabs ----------------------------------------------------------------- */
[data-baseweb="tab-list"] { gap: 24px; border-bottom: 1px solid var(--line); }
[data-baseweb="tab"] { font-size: 14px; font-weight: 500; color: var(--text-2); padding: 8px 0; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--brand); }
[data-baseweb="tab-highlight"] { background-color: var(--brand) !important; }

/* ---- Sidebar household list ---------------------------------------------- */
.cl-brand { display: flex; align-items: center; gap: 10px; margin: 0 0 4px 0; }
.cl-brand-name { font-size: 16px; font-weight: 600; color: var(--brand); }
[class*="st-key-hh"] button {
  width: 100%; justify-content: flex-start; text-align: left; border: 1px solid transparent;
  background: transparent; padding: 8px 10px; min-height: 0;
}
[class*="st-key-hh"] button:hover { background: #EEF1F5; border-color: transparent; }
[class*="st-key-hh"] button p { font-size: 14px; margin: 0; white-space: pre-line; text-align: left; }
[class*="st-key-hhactive_"] button { background: var(--bg); border-color: var(--line); }
[class*="st-key-hhactive_"] button p { font-weight: 600; color: var(--brand); }
.cl-sidebar-foot { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 16px; }

/* ---- Tables --------------------------------------------------------------- */
.cl-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.cl-table th {
  text-align: left; font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-2); padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--surface);
}
.cl-table td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--text); }
.cl-table tr:last-child td { border-bottom: 0; }
.cl-table .sub { color: var(--text-2); font-size: 12px; display: block; margin-top: 2px; }
.cl-table-wrap { border: 1px solid var(--line); border-radius: var(--radius); overflow-x: auto; }

/* ---- Upload file rows ----------------------------------------------------- */
.cl-files { border-top: 1px solid var(--line); margin-top: 8px; }
.cl-file { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
.cl-file-name { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cl-file-meta { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }

/* ---- Stat tiles ------------------------------------------------------------ */
.cl-tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.cl-tile { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; background: var(--bg); }
.cl-tile .v { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text); line-height: 1.2; }
.cl-tile .k { font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-2); }
.cl-tile .k.critical { color: var(--critical); } .cl-tile .k.high { color: var(--high); } .cl-tile .k.review { color: var(--review); }
@media (max-width: 900px) { .cl-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* ---- Cards ---------------------------------------------------------------- */
.cl-card { border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 20px; background: var(--bg); }
.cl-card.quiet { background: var(--surface); }
.cl-card p { margin: 0; }
.cl-notice { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; font-size: 14px;
  background: var(--surface); color: var(--text); margin: 8px 0; }
.cl-notice.warn { border-color: #FEDF89; background: var(--high-bg); }
.cl-notice.error { border-color: #FECDCA; background: var(--critical-bg); }
.cl-notice.ok { border-color: #ABEFC6; background: var(--clear-bg); }
.cl-notice.sample { border-style: dashed; }

/* Finding cards are keyed containers: st-key-finding_<n> */
[class*="st-key-finding_"] { border: 1px solid var(--line); border-radius: var(--radius); padding: 20px 24px 12px; background: var(--bg); }
[class*="st-key-finding_"].settled, [class*="st-key-settled_"] { background: var(--surface); }
.cl-finding-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.cl-finding-title { font-size: 16px; font-weight: 600; color: var(--text); margin: 0; }
.cl-finding-body { font-size: 14px; color: var(--text); line-height: 1.6; margin: 0 0 12px 0; }
.cl-kv { font-size: 14px; color: var(--text); margin: 0 0 12px 0; }
.cl-kv .cl-label { margin-bottom: 4px; }
.cl-decision { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--text-2); margin: 4px 0 8px; }

/* ---- Evidence ledger (signature element) ---------------------------------- */
.cl-ledger { display: grid; grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); align-items: stretch;
  border: 1px solid var(--line); border-radius: var(--radius); margin: 4px 0 16px; overflow: hidden; }
.cl-ledger-col { padding: 14px 16px; min-width: 0; }
.cl-ledger-col.account { background: var(--bg); }
.cl-ledger-col.document { background: var(--bg); }
.cl-ledger-mark { display: flex; align-items: center; justify-content: center; border-left: 1px solid var(--line);
  border-right: 1px solid var(--line); background: var(--surface); color: var(--text-2); font-size: 18px; font-weight: 600; }
.cl-ledger-mark.match { color: var(--text-3); }
.cl-quote { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 10px 12px; font-size: 14px; line-height: 1.55; color: var(--text); margin: 0 0 6px 0;
  overflow-wrap: anywhere; }
.cl-source { font-size: 12px; color: var(--text-2); margin: 0 0 12px 0; }
.cl-source:last-child { margin-bottom: 0; }
.cl-record { margin: 0 0 12px 0; }
.cl-record:last-child { margin-bottom: 0; }
.cl-record-field { font-size: 12px; color: var(--text-2); margin-bottom: 4px; }
.cl-record-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0;
  border-bottom: 1px dashed var(--line); font-size: 14px; color: var(--text); }
.cl-record-row:last-child { border-bottom: 0; }
.cl-record-row .num { font-variant-numeric: tabular-nums; color: var(--text); font-weight: 500; }
.cl-record-row .rel { color: var(--text-2); }
@media (max-width: 760px) {
  .cl-ledger { grid-template-columns: 1fr; }
  .cl-ledger-mark { border: 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 4px 0; }
}

/* ---- Steps (analysis progress) -------------------------------------------- */
.cl-steps { list-style: none; padding: 0; margin: 4px 0; }
.cl-steps li { font-size: 14px; color: var(--text-3); padding: 3px 0; }
.cl-steps li.done { color: var(--text-2); }
.cl-steps li.now { color: var(--text); font-weight: 500; }

/* ---- Chat ------------------------------------------------------------------ */
[data-testid="stChatMessage"] { background: transparent; padding: 8px 0; }
[class*="st-key-chip_"] button { border-radius: 999px; font-size: 13px; padding: 4px 12px; min-height: 0; color: var(--brand); }

/* ---- Expanders, inputs ---------------------------------------------------- */
[data-testid="stExpander"] details { border: 1px solid var(--line); border-radius: var(--radius-sm); }
[data-testid="stExpander"] summary p { font-size: 13px; color: var(--text-2); }
[data-testid="stFileUploaderDropzone"] { background: var(--surface); border: 1px dashed #C9CED6; border-radius: var(--radius); }
textarea, input { font-size: 14px !important; }

/* ---- Footer ---------------------------------------------------------------- */
.cl-footer { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--text-2);
  border-top: 1px solid var(--line); padding-top: 12px; margin-top: 24px; font-variant-numeric: tabular-nums; }
</style>
"""


def apply_theme():
    st.markdown(_CSS, unsafe_allow_html=True)

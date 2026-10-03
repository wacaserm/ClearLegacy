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
/* :where() keeps this at zero specificity so cl-* classes always win. */
:where([data-testid="stMarkdownContainer"]) :where(p, li) { font-size: 14px; line-height: 1.55; }
h1, h2, h3, h4 { font-family: var(--font); color: var(--text); letter-spacing: -0.01em; }
html body .cl-num, html body .cl-table td.num { font-variant-numeric: tabular-nums; }

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
html body .cl-label {
  font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-2); margin: 0 0 8px 0;
}
html body .cl-title { font-size: 24px; font-weight: 600; color: var(--text); margin: 0; line-height: 1.3; letter-spacing: -0.01em; }
html body .cl-section { font-size: 16px; font-weight: 600; color: var(--text); margin: 0 0 8px 0; }
html body .cl-muted { color: var(--text-2); font-size: 14px; }
html body .cl-small { color: var(--text-2); font-size: 12px; }
html body .cl-meta { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 8px; color: var(--text-2); font-size: 14px; }
html body .cl-meta b { color: var(--text); font-weight: 500; }

/* ---- Pills ---------------------------------------------------------------- */
html body .cl-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 500; line-height: 20px; white-space: nowrap;
  border: 1px solid transparent;
}
html body .cl-pill::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
html body .cl-pill.plain::before { display: none; }
html body .cl-pill.critical { color: var(--critical); background: var(--critical-bg); }
html body .cl-pill.high     { color: var(--high); background: var(--high-bg); }
html body .cl-pill.review   { color: var(--review); background: var(--review-bg); }
html body .cl-pill.clear    { color: var(--clear); background: var(--clear-bg); }
html body .cl-pill.neutral  { color: var(--text-2); background: var(--neutral-bg); }
html body .cl-pill.brand    { color: var(--brand); background: #EEF2F8; }
html body .cl-tag {
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
html body .cl-brand { display: flex; align-items: center; gap: 10px; margin: 0 0 4px 0; }
html body .cl-brand-name { font-size: 16px; font-weight: 600; color: var(--brand); }
[class*="st-key-hh"] button {
  width: 100%; justify-content: flex-start; text-align: left; border: 1px solid transparent;
  background: transparent; padding: 8px 10px; min-height: 0;
}
[class*="st-key-hh"] button:hover { background: #EEF1F5; border-color: transparent; }
[class*="st-key-hh"] button p { font-size: 14px; margin: 0; white-space: pre-line; text-align: left; }
[class*="st-key-hh"] button > div, [class*="st-key-hh"] button [data-testid="stMarkdownContainer"] {
  justify-content: flex-start; width: 100%; text-align: left; }
[class*="st-key-hhactive_"] button { background: var(--bg); border-color: var(--line); }
[class*="st-key-hhactive_"] button p { font-weight: 600; color: var(--brand); }
html body .cl-sidebar-foot { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 16px; }

/* ---- Tables --------------------------------------------------------------- */
html body .cl-table { width: 100%; border-collapse: collapse; font-size: 14px; }
html body .cl-table th {
  text-align: left; font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-2); padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--surface);
}
html body .cl-table td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--text); }
html body .cl-table tr:last-child td { border-bottom: 0; }
html body .cl-table .sub { color: var(--text-2); font-size: 12px; display: block; margin-top: 2px; }
html body .cl-table-wrap { border: 1px solid var(--line); border-radius: var(--radius); overflow-x: auto; }

/* ---- Upload file rows ----------------------------------------------------- */
html body .cl-files { border-top: 1px solid var(--line); margin-top: 8px; }
html body .cl-file { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
html body .cl-file-name { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
html body .cl-file-meta { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
html body .cl-chip { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 12px; font-weight: 500;
  color: var(--brand); background: #EEF2F8; white-space: nowrap; }
html body .cl-ready { font-size: 12px; font-weight: 500; color: var(--clear); white-space: nowrap; }

/* ---- Stat tiles ------------------------------------------------------------ */
html body .cl-tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
html body .cl-tile { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; background: var(--bg); }
html body .cl-tile .v { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text); line-height: 1.2; }
html body .cl-tile .k { font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-2); }
html body .cl-tile .k.critical { color: var(--critical); } .cl-tile .k.high { color: var(--high); } .cl-tile .k.review { color: var(--review); }
@media (max-width: 900px) { html body .cl-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* ---- Cards ---------------------------------------------------------------- */
html body .cl-card { border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 20px; background: var(--bg); }
html body .cl-card.quiet { background: var(--surface); }
html body .cl-card p { margin: 0; }
html body .cl-notice { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; font-size: 14px;
  background: var(--surface); color: var(--text); margin: 8px 0; }
html body .cl-notice.warn { border-color: #FEDF89; background: var(--high-bg); }
html body .cl-notice.error { border-color: #FECDCA; background: var(--critical-bg); }
html body .cl-notice.ok { border-color: #ABEFC6; background: var(--clear-bg); }
html body .cl-notice.sample { border-style: dashed; }

/* Finding cards are keyed containers: st-key-finding_<n> */
[class*="st-key-finding_"], [class*="st-key-settled_"] {
  border: 1px solid var(--line); border-radius: var(--radius); padding: 20px 24px 12px; background: var(--bg); }
[class*="st-key-settled_"] { background: var(--surface); }
[class*="st-key-settled_"] .cl-ledger-col { background: var(--bg); }
html body .cl-finding-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
html body .cl-finding-title { font-size: 16px; font-weight: 600; color: var(--text); margin: 0; }
html body .cl-finding-body { font-size: 14px; color: var(--text); line-height: 1.6; margin: 0 0 12px 0; }
html body .cl-kv { font-size: 14px; color: var(--text); margin: 0 0 12px 0; }
html body .cl-kv .cl-label { margin-bottom: 4px; }
html body .cl-decision { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--text-2); margin: 4px 0 8px; }

/* ---- Results header, finding list, document excerpt --------------------- */
html body .cl-results-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end;
  gap: 12px; padding: 4px 0 16px; border-bottom: 1px solid var(--line); margin: 8px 0 8px; }
html body .cl-results-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
[class*="st-key-pick"] button { width: 100%; justify-content: flex-start; text-align: left; background: var(--bg);
  border: 1px solid var(--line); padding: 10px 12px; min-height: 0; margin-bottom: 4px; }
[class*="st-key-pick"] button:hover { background: var(--surface); border-color: #C9CED6; }
[class*="st-key-pick"] button p { font-size: 13px; margin: 0; white-space: pre-line; text-align: left; line-height: 1.45; }
[class*="st-key-pick"] button > div, [class*="st-key-pick"] button [data-testid="stMarkdownContainer"] {
  justify-content: flex-start; width: 100%; text-align: left; }
[class*="st-key-pickactive_"] button { border-color: var(--brand); box-shadow: inset 3px 0 0 var(--brand); background: #F5F7FB; }
[class*="st-key-finding_detail"], [class*="st-key-settled_detail"] {
  border: 1px solid var(--line); border-radius: var(--radius); padding: 20px 24px 12px; background: var(--bg); }
[class*="st-key-settled_detail"] { background: var(--surface); }
html body .cl-page { background: #FFFFFF; border: 1px solid var(--line); border-radius: 6px; margin: 0 0 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
html body .cl-page-head { font-family: var(--font); font-size: 12px; color: var(--text-2); padding: 8px 14px;
  border-bottom: 1px solid var(--line); background: var(--surface); border-radius: 6px 6px 0 0; }
html body .cl-ledger.excerpt { grid-template-columns: minmax(0, 1.5fr) 36px minmax(0, 1fr); }
html body .cl-page-body { font-family: Georgia, 'Times New Roman', serif; font-size: 15px; line-height: 1.7;
  color: var(--text); margin: 0; padding: 14px 16px; overflow-wrap: anywhere; }
html body mark.cl-hl { background: #FFF3B0; color: var(--text); padding: 1px 2px; border-left: 3px solid var(--brand);
  border-radius: 2px; }

/* ---- Evidence ledger (signature element) ---------------------------------- */
html body .cl-ledger { display: grid; grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr); align-items: stretch;
  border: 1px solid var(--line); border-radius: var(--radius); margin: 4px 0 16px; overflow: hidden; }
html body .cl-ledger-col { padding: 14px 16px; min-width: 0; }
html body .cl-ledger-col.account { background: var(--bg); }
html body .cl-ledger-col.document { background: var(--bg); }
html body .cl-ledger-mark { display: flex; align-items: center; justify-content: center; border-left: 1px solid var(--line);
  border-right: 1px solid var(--line); background: var(--surface); color: var(--text-2); font-size: 18px; font-weight: 600; }
html body .cl-ledger-mark.match { color: var(--text-3); }
html body .cl-quote {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 10px 12px; font-size: 14px; line-height: 1.55; color: var(--text); margin: 0 0 6px 0;
  overflow-wrap: anywhere; font-style: normal; }
html body .cl-source { font-size: 12px; color: var(--text-2); margin: 0 0 12px 0; }
html body .cl-source:last-child { margin-bottom: 0; }
html body .cl-record { margin: 0 0 12px 0; }
html body .cl-record:last-child { margin-bottom: 0; }
html body .cl-record-field { font-size: 12px; color: var(--text-2); margin-bottom: 4px; }
html body .cl-record-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0;
  border-bottom: 1px dashed var(--line); font-size: 14px; color: var(--text); }
html body .cl-record-row:last-child { border-bottom: 0; }
html body .cl-record-row .num { font-variant-numeric: tabular-nums; color: var(--text); font-weight: 500; }
html body .cl-record-row .rel { color: var(--text-2); }
@media (max-width: 760px) {
  html body .cl-ledger { grid-template-columns: 1fr; }
  html body .cl-ledger-mark { border: 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 4px 0; }
}

/* ---- Steps (analysis progress) -------------------------------------------- */
html body .cl-steps { list-style: none; padding: 0; margin: 4px 0; }
html body .cl-steps li { font-size: 14px; color: var(--text-3); padding: 3px 0; }
html body .cl-steps li.done { color: var(--text-2); }
html body .cl-steps li.now { color: var(--text); font-weight: 500; }

/* ---- Chat ------------------------------------------------------------------ */
[data-testid="stChatMessage"] { background: transparent; padding: 8px 0; }
[class*="st-key-chip_"] button { border-radius: 999px; font-size: 13px; padding: 4px 12px; min-height: 0; color: var(--brand); }

/* ---- Expanders, inputs ---------------------------------------------------- */
[data-testid="stExpander"] details { border: 1px solid var(--line); border-radius: var(--radius-sm); }
[data-testid="stExpander"] summary p { font-size: 13px; color: var(--text-2); }
[data-testid="stFileUploaderDropzone"] { background: var(--surface); border: 1px dashed #C9CED6; border-radius: var(--radius); }
textarea, input { font-size: 14px !important; }

/* ---- Footer ---------------------------------------------------------------- */
html body .cl-footer { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--text-2);
  border-top: 1px solid var(--line); padding-top: 12px; margin-top: 24px; font-variant-numeric: tabular-nums; }
</style>
"""


def apply_theme():
    st.markdown(_CSS, unsafe_allow_html=True)

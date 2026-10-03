from ui import compat
from ui.html import esc, render


def _card(title, body, tone=""):
    render(f'<div class="cl-card quiet {esc(tone)}"><p class="cl-section">{esc(title)}</p>'
           f'<p class="cl-muted">{esc(body)}</p></div>')


def render_analysis_state(status, error, client_id, sample_available):
    """Empty, processing, failed, and outdated states. Returns True if the sample should load."""
    if status == "failed":
        render('<div class="cl-notice error"><b>Analysis failed.</b> '
               f'{esc(error or "No findings are available for this run.")}</div>')
        render('<p class="cl-small">Check your AWS credentials with <code>python scripts/check_setup.py</code>, '
               "then click Analyze again.</p>")
        return False
    if status == "outdated":
        _card("Results are out of date",
              "The selected documents changed after the last analysis. Click Analyze to review the current files.")
        return False
    if status == "processing":
        _card("Analysis in progress", "Reading documents and comparing them with the accounts on file…")
        return False
    if status == "not_analyzed":
        _card("No analysis yet",
              "Add the client's estate documents above, then click Analyze. "
              "Each finding will show the document quote next to the account record it conflicts with.")
        if sample_available:
            render('<p class="cl-small" style="margin-top:12px">The analysis pipeline is not connected in this '
                   "checkout. You can preview the review flow with fictional sample results.</p>")
            return compat.button("Load sample results", key=f"load_sample_{client_id}")
    return False

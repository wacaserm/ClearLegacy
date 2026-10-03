"""Next steps: what each decision leads to, plus printable summaries for the meetings.

Built from session data only (the current analysis, decisions in session state, and saved
review history). No AI calls and no network calls. All text is escaped.
"""

import html
from datetime import datetime

import streamlit as st

from ui import compat
from ui.findings import comparison_html
from ui.html import esc, humanize_field, parse_record_value, priority_key, quote_text, render
from ui.review import decision_label

PRIORITY_NAMES = {"critical": "Critical", "high": "High", "review": "Review"}
FOOTER = "Not legal advice. Flags are internal and nothing has been sent externally."


def _finding_id(index, finding):
    return finding.get("findingId", f"finding-{index + 1}")


def latest_decisions(analysis, workspace, audit):
    """{findingId: decision record} for this analysis: session decisions first, then saved history."""
    analysis_id = analysis.get("analysisId", "unknown-analysis")
    out = {}
    for record in sorted((r for r in audit or [] if isinstance(r, dict) and r.get("analysisId") == analysis_id),
                         key=lambda r: str(r.get("timestamp", ""))):
        out[record.get("findingId")] = {**record, "reviewer": record.get("reviewer") or record.get("user")}
    for key, record in workspace.get("decisions", {}).items():
        if key.startswith(f"{analysis_id}:"):
            out[key.split(":", 1)[1]] = record
    return out


def group_findings(analysis, workspace, audit):
    """Split the analysis findings by their latest decision."""
    decisions = latest_decisions(analysis, workspace, audit)
    groups = {"confirmed": [], "attorney_review": [], "dismissed": [], "open": []}
    findings = sorted(enumerate(analysis.get("findings", []) or []),
                      key=lambda pair: ({"critical": 0, "high": 1, "review": 2}[priority_key(pair[1].get("priority"))], pair[0]))
    for index, finding in findings:
        decision = decisions.get(_finding_id(index, finding))
        kind = (decision or {}).get("decision")
        kind = {"confirm": "confirmed", "dismiss": "dismissed"}.get(kind, kind)
        groups.get(kind if decision else "open", groups["open"]).append((finding, decision))
    return groups


def clarifying_questions(analysis):
    """The analysis's clarifying questions as plain strings (blank entries dropped)."""
    return [" ".join(str(q).split()) for q in (analysis or {}).get("clarificationQuestions", []) or [] if str(q).strip()]


def _who_when(decision):
    when = str((decision or {}).get("timestamp", ""))[:16].replace("T", " ")
    who = (decision or {}).get("reviewer") or "Reviewer not recorded"
    return f"{who} · {when}" if when else who


# --------------------------------------------------------------------------- on-screen view

def _item(finding, decision, body):
    label, tone = decision_label((decision or {}).get("decision")) if decision else ("Open", "neutral")
    priority = priority_key(finding.get("priority"))
    render('<div class="cl-card" style="margin-bottom:12px">'
           f'<div class="cl-finding-head"><span class="cl-pill {priority}">{PRIORITY_NAMES[priority]}</span>'
           + (f'<span class="cl-pill {tone} plain">{esc(label)}</span>' if decision else "") + "</div>"
           f'<p class="cl-finding-title">{quote_text(finding.get("title", "Finding"))}</p>{body}</div>')


def _empty(text):
    render(f'<div class="cl-card quiet" style="margin-bottom:12px"><p class="cl-muted">{esc(text)}</p></div>')


def render_next_steps(client_name, analysis, workspace, audit, reviewer, sample=False):
    if analysis is None:
        _empty("Run an analysis and record decisions. Confirmed items, items for the attorney, and "
               "documented dismissals will be organized here.")
        return
    groups = group_findings(analysis, workspace, audit)
    questions = clarifying_questions(analysis)
    names = analysis.get("sourceNames") or {}
    documents = analysis.get("documents") or []
    if sample:
        render('<div class="cl-notice sample"><b>Sample results.</b> Not produced from your uploaded files.</div>')

    total = sum(len(v) for v in groups.values())
    render(f'<p class="cl-muted" style="margin:0 0 16px">{total - len(groups["open"])} of {total} items decided. '
           "Nothing here is sent to anyone; use the downloads to prepare for meetings.</p>")

    columns = st.columns(2)
    with columns[0]:
        compat.download_button(
            "Download attorney review summary",
            data=build_summary_html("attorney", client_name, analysis, groups, reviewer),
            file_name=_file_name(client_name, "attorney-review"),
            mime="text/html", key="download_attorney", stretch=True,
            disabled=not groups["attorney_review"],
        )
    with columns[1]:
        compat.download_button(
            "Download client follow-up list",
            data=build_summary_html("client", client_name, analysis, groups, reviewer),
            file_name=_file_name(client_name, "client-follow-up"),
            mime="text/html", key="download_client", stretch=True,
            disabled=not (groups["confirmed"] or questions),
        )

    render('<p class="cl-section" style="margin-top:24px">Follow up with the client</p>')
    if not groups["confirmed"]:
        _empty("No confirmed items yet. Confirm a finding to add it to the client follow-up list.")
    for finding, decision in groups["confirmed"]:
        body = ""
        follow_up = finding.get("followUpQuestion") or finding.get("clarificationQuestion")
        if follow_up:
            body += f'<div class="cl-kv"><p class="cl-label">Ask the client</p>{quote_text(follow_up)}</div>'
        if finding.get("recommendedAction"):
            body += f'<div class="cl-kv"><p class="cl-label">Recommended next step</p>{quote_text(finding["recommendedAction"])}</div>'
        body += _decision_line(decision)
        _item(finding, decision, body)
    if questions:
        render('<div class="cl-card" style="margin-bottom:12px"><p class="cl-label">Questions to ask the client</p>'
               '<ul style="margin:6px 0 0;padding-left:20px">'
               + "".join(f'<li style="margin:2px 0">{esc(q)}</li>' for q in questions) + "</ul></div>")

    render('<p class="cl-section" style="margin-top:24px">For the client\'s attorney</p>')
    if not groups["attorney_review"]:
        _empty("No items flagged for the attorney yet.")
    for finding, decision in groups["attorney_review"]:
        evidence = finding.get("evidence", []) if isinstance(finding.get("evidence"), list) else []
        body = (f'<p class="cl-finding-body" style="margin-top:8px">{quote_text(finding.get("explanation", ""))}</p>'
                + comparison_html(evidence, names, documents) + _decision_line(decision))
        _item(finding, decision, body)

    render('<p class="cl-section" style="margin-top:24px">Dismissed (documented)</p>')
    if not groups["dismissed"]:
        _empty("No dismissed items. Dismissals need a short reason so the review history explains them.")
    for finding, decision in groups["dismissed"]:
        _item(finding, decision, _decision_line(decision, label="Reason"))

    render(f'<p class="cl-section" style="margin-top:24px">Still to review <span class="cl-small">· {len(groups["open"])}</span></p>')
    if not groups["open"]:
        _empty("Every item has a decision.")
    else:
        render('<div class="cl-card quiet">' + "".join(
            f'<p style="margin:4px 0"><span class="cl-pill {priority_key(f.get("priority"))}">'
            f'{PRIORITY_NAMES[priority_key(f.get("priority"))]}</span> {quote_text(f.get("title", "Finding"))}</p>'
            for f, _ in groups["open"]) + "</div>")
    render(f'<p class="cl-small" style="margin-top:16px">{esc(FOOTER)}</p>')


def _decision_line(decision, label="Note"):
    note = (decision or {}).get("note")
    text = f"{label}: {note}" if note else "No note"
    return f'<p class="cl-small" style="margin-top:4px">{quote_text(text)} · {esc(_who_when(decision))}</p>'


def _file_name(client_name, kind):
    slug = "-".join(str(client_name or "household").lower().split())
    return f"clearlegacy-{slug}-{kind}-{datetime.now().strftime('%Y-%m-%d')}.html"


# --------------------------------------------------------------------------- printable files

_PRINT_CSS = """
body { font-family: Inter, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif; color: #0B1220; max-width: 760px;
  margin: 32px auto; padding: 0 20px; line-height: 1.55; font-size: 14px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; }
.meta { color: #475467; font-size: 13px; margin: 0 0 20px; }
.item { border: 1px solid #E4E7EC; border-radius: 8px; padding: 14px 16px; margin: 0 0 14px; page-break-inside: avoid; }
.label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: #475467; margin: 10px 0 2px; }
.priority { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.quote { font-family: Georgia, serif; background: #FFF9DB; border-left: 3px solid #00205B; padding: 8px 12px; margin: 4px 0; }
.source, .who { color: #475467; font-size: 12px; }
table { border-collapse: collapse; width: 100%; margin: 4px 0; } td { border-top: 1px solid #E4E7EC; padding: 4px 6px; font-size: 13px; }
footer { border-top: 1px solid #E4E7EC; margin-top: 28px; padding-top: 10px; color: #475467; font-size: 12px; }
"""


def _account_rows(item):
    field = humanize_field(item.get("field"))
    rows = parse_record_value(item.get("value"))
    if rows is None:
        cells = f"<tr><td>{html.escape(str(item.get('value', '')))}</td></tr>"
    else:
        cells = "".join(
            "<tr><td>" + html.escape(" · ".join(str(v) for k, v in r.items() if k in ("name", "relationship") and v))
            + "</td><td>" + html.escape(f"{r['percentage']}%" if r.get("percentage") is not None else "") + "</td></tr>"
            for r in rows) or "<tr><td>None listed</td></tr>"
    return (f'<p class="source">{html.escape(str(item.get("sourceId", "Account")))} · {html.escape(field)}</p>'
            f"<table>{cells}</table>")


def _evidence_html(finding, names):
    out = []
    for item in finding.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("sourceType") == "document":
            source = item.get("filename") or names.get(item.get("sourceId")) or "Document"
            out.append('<p class="label">Document says</p>'
                       f'<div class="quote">{html.escape(" ".join(str(item.get("quote", "")).split()))}</div>'
                       f'<p class="source">{html.escape(source)} · {html.escape(str(item.get("location", "")))}</p>')
        elif item.get("sourceType") == "account":
            out.append('<p class="label">Account record says</p>' + _account_rows(item))
    return "".join(out)


def build_summary_html(kind, client_name, analysis, groups, reviewer) -> str:
    """Printable HTML for the attorney meeting ('attorney') or the client follow-up list ('client')."""
    attorney = kind == "attorney"
    items = groups["attorney_review"] if attorney else groups["confirmed"]
    questions = [] if attorney else clarifying_questions(analysis)
    names = analysis.get("sourceNames") or {}
    title = "Attorney review summary" if attorney else "Client follow-up list"
    purpose = ("Prepared by ClearLegacy for review with the client's attorney" if attorney
               else "Prepared by ClearLegacy for follow-up with the client")
    e = lambda v: html.escape(" ".join(str(v or "").split()))  # noqa: E731
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)} - {e(client_name)}</title>"
             f"<style>{_PRINT_CSS}</style></head><body>",
             f"<h1>{e(title)}: {e(client_name or 'Household')}</h1>",
             f'<p class="meta">{e(purpose)}<br>Date: {datetime.now().strftime("%B %d, %Y")} · '
             f"Reviewer: {e(reviewer or 'Not recorded')} · {len(items)} item{'s' if len(items) != 1 else ''}</p>"]
    if not items and not questions:
        parts.append("<p>No items yet.</p>")
    for finding, decision in items:
        priority = PRIORITY_NAMES[priority_key(finding.get("priority"))]
        block = [f'<div class="item"><p class="priority">{e(priority)}</p><h2 style="margin-top:2px">{e(finding.get("title", "Finding"))}</h2>',
                 f"<p>{e(finding.get('explanation', ''))}</p>"]
        if not attorney:
            follow_up = finding.get("followUpQuestion") or finding.get("clarificationQuestion")
            if follow_up:
                block.append(f'<p class="label">Ask the client</p><p>{e(follow_up)}</p>')
            if finding.get("recommendedAction"):
                block.append(f'<p class="label">Recommended next step</p><p>{e(finding["recommendedAction"])}</p>')
        block.append(_evidence_html(finding, names))
        note = (decision or {}).get("note")
        block.append(f'<p class="label">Advisor note</p><p>{e(note) if note else "No note"}</p>'
                     f'<p class="who">Decided by {e(_who_when(decision))}</p></div>')
        parts.append("".join(block))
    if questions:
        parts.append('<div class="item"><h2 style="margin-top:2px">Questions to ask the client</h2><ul>'
                     + "".join(f"<li>{e(q)}</li>" for q in questions) + "</ul></div>")
    parts.append(f"<footer>{e(FOOTER)}</footer></body></html>")
    return "".join(parts)

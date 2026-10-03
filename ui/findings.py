import re

import streamlit as st

from ui.html import (
    PRIORITY_ORDER, esc, format_percentage, humanize_field, parse_record_value,
    priority_key, priority_pill, quote_text, render,
)
from ui.aws_status import advisor_message, remember_technical
from ui.review import decision_label, render_finding_actions

_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")


def md_escape(text) -> str:
    """Escape Markdown so untrusted text renders literally in widget labels."""
    return _MD_SPECIAL.sub(r"\\\1", str(text or ""))


# --------------------------------------------------------------------------- evidence ledger

def _document_block(item, names):
    source = item.get("filename") or names.get(item.get("sourceId")) or "Document"
    location = item.get("location") or "location not supplied"
    quote = item.get("quote") or item.get("value") or "Quote not supplied."
    return (f'<div class="cl-quote" role="note">{quote_text(quote)}</div>'
            f'<p class="cl-source">{esc(source)} · {esc(location)}</p>')


def _record_rows(value):
    rows = parse_record_value(value)
    if rows is None:
        return f'<div class="cl-record-row"><span>{esc(value if value not in (None, "") else "Not provided")}</span></div>'
    if not rows:
        return '<div class="cl-record-row"><span class="rel">None listed</span></div>'
    out = []
    for row in rows:
        name = row.get("name")
        if name:
            share = format_percentage(row.get("percentage", row.get("allocation")))
            relationship = row.get("relationship")
            left = esc(name) + (f' <span class="rel">· {esc(relationship)}</span>' if relationship else "")
            out.append(f'<div class="cl-record-row"><span>{left}</span><span class="num">{esc(share)}</span></div>')
        else:
            text = " · ".join(f"{humanize_field(k)}: {v}" for k, v in row.items())
            out.append(f'<div class="cl-record-row"><span>{esc(text)}</span></div>')
    return "".join(out)


def _account_block(item):
    if item.get("quote"):  # fixture samples quote the account snapshot instead of a field
        source = item.get("filename") or item.get("sourceId") or "Account record"
        return (f'<div class="cl-quote" role="note">{quote_text(item["quote"])}</div>'
                f'<p class="cl-source">{esc(source)} · {esc(item.get("location") or "supplied record")}</p>')
    field = humanize_field(item.get("field"))
    source = item.get("sourceId") or "Account record"
    return (f'<div class="cl-record"><div class="cl-record-field">{esc(source)} · {esc(field)}</div>'
            f'{_record_rows(item.get("value"))}</div>')


def ledger_html(evidence, names=None) -> str:
    """The evidence ledger: what the document says next to what the account record says."""
    names = names or {}
    evidence = [e for e in evidence if isinstance(e, dict)]
    documents = [e for e in evidence if e.get("sourceType") == "document"]
    accounts = [e for e in evidence if e.get("sourceType") == "account"]
    left = "".join(_document_block(e, names) for e in documents) or '<p class="cl-muted">No document quote supplied.</p>'
    right = "".join(_account_block(e) for e in accounts) or '<p class="cl-muted">No account record supplied.</p>'
    mismatch = bool(documents and accounts)
    mark = ('<div class="cl-ledger-mark" role="img" aria-label="Does not match" title="Does not match">≠</div>'
            if mismatch else '<div class="cl-ledger-mark match" aria-hidden="true">·</div>')
    return (
        '<div class="cl-ledger">'
        f'<div class="cl-ledger-col document"><p class="cl-label">Document says</p>{left}</div>'
        f"{mark}"
        f'<div class="cl-ledger-col account"><p class="cl-label">Account record says</p>{right}</div>'
        "</div>"
    )


# --------------------------------------------------------------------------- overview

def _decisions_for(analysis_id, findings, workspace):
    keys = {f"{analysis_id}:{f.get('findingId', f'finding-{i + 1}')}" for i, f in enumerate(findings)}
    return {k: v for k, v in workspace["decisions"].items() if k in keys}


def _tiles(findings, questions, decided):
    counts = {"critical": 0, "high": 0, "review": 0}
    for finding in findings:
        counts[priority_key(finding.get("priority"))] += 1
    tiles = [
        (str(counts["critical"]), "Critical", "critical"),
        (str(counts["high"]), "High", "high"),
        (str(counts["review"]), "Review", "review"),
        (str(len(questions)), "Questions", ""),
        (f"{decided} of {len(findings)}" if findings else "—", "Decisions made", ""),
    ]
    render('<div class="cl-tiles">' + "".join(
        f'<div class="cl-tile"><div class="k {tone}">{esc(label)}</div><div class="v">{esc(value)}</div></div>'
        for value, label, tone in tiles) + "</div>")


_STATUS_NOTICE = {
    "no_discrepancies_found": ("ok", "No discrepancies found within the supplied documents and account records."),
    "needs_information": ("warn", "More information is needed to complete this review. See the questions below."),
    "review_needed": ("", "Review each finding with the client, then record a decision."),
}


# --------------------------------------------------------------------------- findings

def render_findings(client_id, analysis, workspace, sample=False):
    if not analysis:
        return None
    findings = sorted(
        enumerate(analysis.get("findings", []) or []),
        key=lambda pair: (PRIORITY_ORDER.get(priority_key(pair[1].get("priority")), 9), pair[0]),
    )
    questions = analysis.get("clarificationQuestions", []) or []
    analysis_id = analysis.get("analysisId", "unknown-analysis")
    names = analysis.get("sourceNames") or {}
    decisions = _decisions_for(analysis_id, [f for _, f in findings], workspace)

    if sample:
        render('<div class="cl-notice sample"><b>Sample results.</b> These fictional findings were not produced '
               "from your uploaded files and are shown for demonstration only.</div>")
    tone, text = _STATUS_NOTICE.get(analysis.get("status"), ("", ""))
    if text:
        render(f'<div class="cl-notice {tone}">{esc(text)}</div>')

    _tiles([f for _, f in findings], questions, len(decisions))

    if analysis.get("summary"):
        render('<div class="cl-card quiet"><p class="cl-label">Case summary</p>'
               f'<p style="font-size:14px;line-height:1.6">{quote_text(analysis["summary"])}</p>'
               '<p class="cl-small" style="margin-top:8px">AI-generated from the findings below. Review the evidence before acting.</p></div>')

    shown = []
    for warning in analysis.get("warnings", []) or []:
        message = advisor_message(warning)  # AWS fallbacks get advisor wording; detail goes to System details
        if message:
            remember_technical(warning)
        message = message or warning
        if message not in shown:
            shown.append(message)
            render(f'<div class="cl-notice warn">{esc(message)}</div>')

    event = None
    if findings:
        render(f'<p class="cl-section" style="margin-top:24px">Findings <span class="cl-small">· {len(findings)}</span></p>')
    elif analysis.get("status") == "review_needed" and not questions:
        render('<div class="cl-notice">The analysis requested review but returned no findings.</div>')

    for position, (index, finding) in enumerate(findings):
        finding_id = finding.get("findingId", f"finding-{index + 1}")
        decision = decisions.get(f"{analysis_id}:{finding_id}")
        container_key = f"settled_{position}" if decision else f"finding_{position}"
        with st.container(key=container_key):
            head = priority_pill(finding.get("priority"))
            if decision:
                label, tone = decision_label(decision.get("decision"))
                head += f' <span class="cl-pill {esc(tone)} plain">{esc(label)}</span>'
            render(f'<div class="cl-finding-head">{head}</div>'
                   f'<p class="cl-finding-title">{quote_text(finding.get("title", "Finding"))}</p>')
            render(f'<p class="cl-finding-body" style="margin-top:8px">{quote_text(finding.get("explanation", "No explanation was provided."))}</p>')
            if finding.get("recommendedAction"):
                render(f'<div class="cl-kv"><p class="cl-label">Recommended action</p>{quote_text(finding["recommendedAction"])}</div>')
            follow_up = finding.get("followUpQuestion") or finding.get("clarificationQuestion")
            if follow_up:
                render(f'<div class="cl-kv"><p class="cl-label">Follow-up question</p>{quote_text(follow_up)}</div>')

            evidence = finding.get("evidence", [])
            render(ledger_html(evidence if isinstance(evidence, list) else [], names))

            if decision:
                note = decision.get("note")
                reviewer = decision.get("reviewer")
                parts = [str(decision.get("timestamp", ""))[:16].replace("T", " ")]
                if reviewer and reviewer != "Not provided":
                    parts.insert(0, reviewer)
                if note:
                    parts.append(f"Note: {note}")
                render(f'<p class="cl-small">{quote_text(" · ".join(p for p in parts if p))}</p>')
                with st.expander("Change decision"):
                    event = render_finding_actions(client_id, analysis_id, finding_id, decision.get("decision"), sample) or event
            else:
                event = render_finding_actions(client_id, analysis_id, finding_id, None, sample) or event
            

    if questions:
        render('<p class="cl-section" style="margin-top:24px">Clarifying questions</p>'
               '<p class="cl-small" style="margin:-4px 0 8px">Tick each question once it has been raised with the client.</p>')
        for i, question in enumerate(questions):
            st.checkbox(md_escape(question), key=f"question_{analysis_id}_{i}")

    return event

import re

import streamlit as st

from ui.html import (
    PRIORITY_ORDER, esc, format_percentage, humanize_field, parse_record_value,
    priority_key, priority_pill, quote_text, render,
)
from ui import compat
from ui.aws_status import advisor_message, remember_technical
from ui.excerpt import find_context, highlight_html, short_title
from ui.overview import render_overview
from ui.review import decision_label, render_finding_actions, render_reviewer_field

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

def comparison_html(evidence, names=None, documents=None) -> str:
    """Evidence comparison: document excerpt (quote highlighted in context) next to what is on file."""
    names = names or {}
    evidence = [e for e in evidence if isinstance(e, dict)]
    docs = [e for e in evidence if e.get("sourceType") == "document"]
    accounts = [e for e in evidence if e.get("sourceType") == "account"]
    excerpts = []
    for item in docs:
        source = item.get("filename") or names.get(item.get("sourceId")) or "Document"
        location = item.get("location") or "location not supplied"
        context = find_context(item.get("quote"), item.get("sourceId"), item.get("location"), documents)
        body = highlight_html(context or "", item.get("quote") or item.get("value") or "")
        excerpts.append(f'<div class="cl-page"><div class="cl-page-head">{esc(source)} · {esc(location)}</div>'
                        f'<p class="cl-page-body">{body}</p></div>')
    left = "".join(excerpts) or '<p class="cl-muted">No document excerpt supplied.</p>'
    right = "".join(_account_block(e) for e in accounts) or '<p class="cl-muted">No account record supplied.</p>'
    mismatch = bool(docs and accounts)
    mark = ('<div class="cl-ledger-mark" role="img" aria-label="Does not match" title="Does not match">≠</div>'
            if mismatch else '<div class="cl-ledger-mark match" aria-hidden="true">·</div>')
    return ('<div class="cl-ledger excerpt">'
            f'<div class="cl-ledger-col document"><p class="cl-label">Document excerpt</p>{left}</div>'
            f"{mark}"
            f'<div class="cl-ledger-col account"><p class="cl-label">On file</p>{right}</div>'
            "</div>")


def default_selection(findings, decisions, analysis_id):
    """First undecided critical finding, else first undecided, else the first."""
    def finding_id(index, finding):
        return finding.get("findingId", f"finding-{index + 1}")
    undecided = [(i, f) for i, f in findings if f"{analysis_id}:{finding_id(i, f)}" not in decisions]
    for i, f in undecided:
        if priority_key(f.get("priority")) == "critical":
            return finding_id(i, f)
    if undecided:
        return finding_id(*undecided[0])
    return finding_id(*findings[0]) if findings else None


def _header(client_name, findings, questions, decided):
    counts = {"critical": 0, "high": 0, "review": 0}
    for _, finding in findings:
        counts[priority_key(finding.get("priority"))] += 1
    items = len(findings)
    chips = "".join(f'<span class="cl-pill {k}">{esc(PRIORITY_LABELS_PLURAL[k])}: {counts[k]}</span>'
                    for k in ("critical", "high", "review") if counts[k])
    text = f"{items} item{'s' if items != 1 else ''} to review" if items else "No items to review"
    if questions:
        text += f" · {len(questions)} question{'s' if len(questions) != 1 else ''} for the client"
    render('<div class="cl-results-head">'
           f'<div><p class="cl-label" style="margin:0 0 2px">Review</p><p class="cl-section" style="margin:0">'
           f'{esc(client_name or "Household")} · {esc(text)}</p></div>'
           f'<div class="cl-results-meta">{chips}<span class="cl-small">Decisions made '
           f'<b class="cl-num">{decided} of {items}</b></span></div></div>')


PRIORITY_LABELS_PLURAL = {"critical": "Critical", "high": "High", "review": "Review"}


def render_findings(client_id, analysis, workspace, sample=False, client_name=None, accounts=None):
    if not analysis:
        return None
    findings = sorted(
        enumerate(analysis.get("findings", []) or []),
        key=lambda pair: (PRIORITY_ORDER.get(priority_key(pair[1].get("priority")), 9), pair[0]),
    )
    questions = analysis.get("clarificationQuestions", []) or []
    analysis_id = analysis.get("analysisId", "unknown-analysis")
    names = analysis.get("sourceNames") or {}
    documents = analysis.get("documents") or []
    decisions = _decisions_for(analysis_id, [f for _, f in findings], workspace)

    if sample:
        render('<div class="cl-notice sample"><b>Sample results.</b> These fictional findings were not produced '
               "from your uploaded files and are shown for demonstration only.</div>")
    _header(client_name, findings, questions, len(decisions))
    tone, text = _STATUS_NOTICE.get(analysis.get("status"), ("", ""))
    if text and analysis.get("status") != "review_needed":
        render(f'<div class="cl-notice {tone}">{esc(text)}</div>')

    render_overview(accounts or [], [f for _, f in findings], names)

    if analysis.get("summary"):
        render('<div class="cl-card quiet" style="margin-top:16px"><p class="cl-label">Case summary</p>'
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
        select_key = f"clearlegacy_selected_{analysis_id}"
        ids = [f.get("findingId", f"finding-{i + 1}") for i, f in findings]
        if st.session_state.get(select_key) not in ids:
            st.session_state[select_key] = default_selection(findings, decisions, analysis_id)
        selected = st.session_state[select_key]

        title_column, reviewer_column = st.columns([2, 1], vertical_alignment="bottom")
        with title_column:
            render('<p class="cl-section" style="margin-top:24px">Items to review</p>')
        with reviewer_column:
            render_reviewer_field()
        list_column, detail_column = st.columns([1, 2.3], gap="large")
        with list_column:
            for position, (index, finding) in enumerate(findings):
                finding_id = ids[position]
                decision = decisions.get(f"{analysis_id}:{finding_id}")
                state = decision_label(decision.get("decision"))[0] if decision else "Open"
                label = (f"**{PRIORITY_LABELS_PLURAL[priority_key(finding.get('priority'))]}** · {state}\n"
                         f"{md_escape(short_title(finding.get('title', 'Finding'), 64))}")
                key = f"pickactive_{position}" if finding_id == selected else f"pick_{position}"
                if compat.button(label, key=key, stretch=True) and finding_id != selected:
                    st.session_state[select_key] = finding_id
                    st.rerun()

        position = ids.index(selected)
        index, finding = findings[position]
        decision = decisions.get(f"{analysis_id}:{selected}")
        with detail_column:
            with st.container(key=f"settled_detail" if decision else "finding_detail"):
                head = priority_pill(finding.get("priority"))
                if decision:
                    label, tone_ = decision_label(decision.get("decision"))
                    head += f' <span class="cl-pill {esc(tone_)} plain">{esc(label)}</span>'
                render(f'<div class="cl-finding-head">{head}</div>'
                       f'<p class="cl-finding-title">{quote_text(finding.get("title", "Finding"))}</p>')
                render(f'<p class="cl-finding-body" style="margin-top:8px">{quote_text(finding.get("explanation", "No explanation was provided."))}</p>')
                follow_up = finding.get("followUpQuestion") or finding.get("clarificationQuestion")
                if follow_up:
                    render(f'<div class="cl-kv"><p class="cl-label">Ask the client</p>{quote_text(follow_up)}</div>')
                if finding.get("recommendedAction"):
                    render(f'<div class="cl-kv"><p class="cl-label">Recommended next step</p>{quote_text(finding["recommendedAction"])}</div>')
                evidence = finding.get("evidence", [])
                render(comparison_html(evidence if isinstance(evidence, list) else [], names, documents))
                if decision:
                    reviewer = decision.get("reviewer")
                    parts = [str(decision.get("timestamp", ""))[:16].replace("T", " ")]
                    if reviewer and reviewer != "Not provided":
                        parts.insert(0, reviewer)
                    if decision.get("note"):
                        parts.append(f"Note: {decision['note']}")
                    render(f'<p class="cl-small">{quote_text(" · ".join(p for p in parts if p))}</p>')
                    with st.expander("Change decision"):
                        event = render_finding_actions(client_id, analysis_id, selected, decision.get("decision"), sample) or event
                else:
                    event = render_finding_actions(client_id, analysis_id, selected, None, sample) or event
    elif analysis.get("status") == "review_needed" and not questions:
        render('<div class="cl-notice">The analysis requested review but returned no findings.</div>')

    if questions:
        render('<p class="cl-section" style="margin-top:24px">Clarifying questions</p>'
               '<p class="cl-small" style="margin:-4px 0 8px">Tick each question once it has been raised with the client.</p>')
        for i, question in enumerate(questions):
            st.checkbox(md_escape(question), key=f"question_{analysis_id}_{i}")
    return event

"""Headless render of every UI state with Streamlit's AppTest. No AWS or Bedrock calls."""

import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services import gui_adapter
from ui.state import fingerprint_documents

APP = str(Path(__file__).resolve().parent.parent / "app.py")
XSS = '<script>alert("x")</script>'

LIVE = {
    "analysisId": "analysis-test",
    "status": "review_needed",
    "summary": "Four items were flagged for Jordan Morgan.",
    "findings": [
        {"findingId": "F-review", "priority": "review", "title": "Document governed by FL; client lives in GA",
         "explanation": "The will names Florida law.", "recommendedAction": "Confirm with the client.",
         "evidence": [{"sourceType": "document", "sourceId": "s1", "location": "page 1", "quote": "governed by the laws of Florida"},
                      {"sourceType": "account", "sourceId": "morgan", "field": "state", "value": "GA"}]},
        {"findingId": "F-critical", "priority": "critical", "title": f"TOD differs from will {XSS}",
         "explanation": "Mismatch.", "recommendedAction": "Review with attorney.", "followUpQuestion": "Intentional?",
         "evidence": [{"sourceType": "document", "sourceId": "s1", "location": "page 2", "quote": f"residue to Casey {XSS}"},
                      {"sourceType": "account", "sourceId": "DEMO-MORGAN-BROKERAGE", "field": "primaryBeneficiaries",
                       "value": '[{"name": "Avery Morgan", "percentage": 50, "relationship": "child"}, {"name": "Riley Morgan", "percentage": 50}]'}]},
        {"findingId": "F-high", "priority": "high", "title": "POA agent marked deceased", "explanation": "x",
         "recommendedAction": "y", "evidence": [{"sourceType": "document", "sourceId": "s2", "location": "page 1", "quote": "Pat Morgan"}]},
    ],
    "clarificationQuestions": ["No successor agent named in the POA [link](http://x)"],
    "warnings": ["A sample warning"],
    "usage": {"models": {"us.anthropic.claude-sonnet-5": {"calls": 3, "inputTokens": 9000, "outputTokens": 2000, "estimatedCostUSD": 0.038},
                         "us.anthropic.claude-haiku-4-5-20251001-v1:0": {"calls": 4, "inputTokens": 2000, "outputTokens": 500, "estimatedCostUSD": 0.0045}},
              "estimatedCostUSD": 0.0425},
    "elapsedSeconds": 24.2,
    "sourceNames": {"s1": "morgan_will_summary.pdf", "s2": "morgan_poa_summary.pdf"},
}


def _workspace(status="not_analyzed", result=None, source="live", decisions=None, history=None):
    # Fingerprint of "no files selected", so the app doesn't mark injected results outdated.
    ws = {"upload_fingerprint": fingerprint_documents([]), "status": status, "current_analysis_id": None, "analyses": {},
          "decisions": decisions or {}, "history": history or [], "notice": None,
          "error": "Bedrock call failed: expired" if status == "failed" else None, "processing": status == "processing"}
    if result is not None:
        ws["current_analysis_id"] = result["analysisId"]
        ws["analyses"][result["analysisId"]] = {"result": result, "source": source,
                                                 "upload_fingerprint": fingerprint_documents([]), "outdated": False}
    return ws


def _run(selected="morgan", show_details=False, reviewer=None, **workspace_kwargs):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["clearlegacy_ui"] = {"selected_client_id": selected,
                                          "workspaces": {selected: _workspace(**workspace_kwargs)}}
    at.session_state["clearlegacy_show_system_details"] = show_details
    if reviewer is not None:
        at.session_state["clearlegacy_reviewer"] = reviewer
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _html(at):
    return "\n".join(str(m.value) for m in at.markdown)


@pytest.mark.parametrize("household", ["morgan", "patel", "rivera"])
def test_empty_state_each_household(household):
    at = _run(selected=household)
    assert "No analysis yet" in _html(at)
    assert [t.label for t in at.tabs] == ["Findings", "Next steps", "Ask ClearLegacy", "Review history"]


def test_live_result_master_detail_comparison_and_details():
    decided = {"analysis-test:F-high": {"analysisId": "analysis-test", "findingId": "F-high", "decision": "confirmed",
                                        "note": "Spoke with client", "reviewer": "Advisor", "timestamp": "2026-10-02T20:00"}}
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), decisions=decided, show_details=True)
    picks = [b.label for b in at.button if b.key and b.key.startswith("pick")]
    assert [p.split("**")[1] for p in picks] == ["Critical", "High", "Review"]  # sorted by priority
    assert "Confirmed" in picks[1] and "Open" in picks[0]  # decided state shown in the list
    html = _html(at)
    assert "3 items to review" in html and "1 of 3" in html
    assert "Document excerpt" in html and "On file" in html and "≠" in html
    assert "TOD differs" in html  # default selection: first undecided critical
    assert "Avery Morgan" in html and "50%" in html  # account JSON shown as readable rows
    assert XSS not in html and "&lt;script&gt;" in html  # untrusted text is escaped
    assert "Who gets what" in html and "Est. cost" in html and "Claude Sonnet 5" in html
    assert any(c.label.startswith("No successor agent") for c in at.checkbox)


def test_selecting_a_finding_switches_the_detail():
    at = _run(status="review_needed", result=copy.deepcopy(LIVE))
    review_button = next(b for b in at.button if b.key and b.key.startswith("pick") and "**Review**" in b.label)
    review_button.click().run()
    assert not at.exception
    html = _html(at)
    assert "governed by the laws of Florida" in html  # the review finding's excerpt is now shown


def test_excerpt_highlights_quote_in_context_and_escapes():
    from ui.excerpt import find_context, highlight_html
    docs = [{"sourceId": "s1", "sections": [
        {"location": "page 1", "text": "Intro.\n\nI give the residue  of my estate to <b>Casey</b> Morgan. End."}]}]
    context = find_context("i give the residue of my estate to <b>casey</b>", "s1", "page 1", docs)
    html = highlight_html(context, "i give the residue of my estate to <b>casey</b>")
    assert '<mark class="cl-hl">I give the residue of my estate to &lt;b&gt;Casey&lt;/b&gt;</mark>' in html
    assert html.startswith("Intro.") and "<b>" not in html
    assert highlight_html(None, "<script>x</script>") == '<mark class="cl-hl">&lt;script&gt;x&lt;/script&gt;</mark>'


def test_who_gets_what_statuses():
    from ui.overview import account_status
    findings = [{"priority": "critical", "title": "TOD issue for DEMO-MORGAN-BROKERAGE", "evidence": []},
                {"priority": "review", "title": "x", "evidence": [{"sourceType": "account", "sourceId": "DEMO-MORGAN-IRA"}]}]
    assert account_status("DEMO-MORGAN-BROKERAGE", findings)[0] == "mismatch"
    assert account_status("DEMO-MORGAN-IRA", findings)[0] == "review"
    assert account_status("DEMO-OTHER", findings)[0] == "none"


def test_sample_result_is_labeled():
    at = _run(status="review_needed", result=gui_adapter.sample_analysis("morgan") | {"analysisId": "sample-morgan"}, source="sample")
    assert "Sample results." in _html(at)


@pytest.mark.parametrize("status", ["needs_information", "no_discrepancies_found"])
def test_other_result_statuses(status):
    result = copy.deepcopy(LIVE) | {"status": status, "findings": [], "summary": None}
    at = _run(status=status, result=result)
    assert ("More information is needed" if status == "needs_information" else "No discrepancies found") in _html(at)


@pytest.mark.parametrize("status,text", [("failed", "Analysis failed."), ("outdated", "Results are out of date"),
                                         ("processing", "Analysis in progress")])
def test_failed_outdated_processing_states(status, text):
    assert text in _html(_run(status=status))


def test_review_history_table_and_masking_note(monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_PII_MASKING", "1")
    history = [{"analysisId": "a", "findingId": "F1", "decision": "attorney_review", "note": "Call [PHONE]",
                "reviewer": "Advisor", "timestamp": "2026-10-02T20:00", "persistence": "Session-only"}]
    html = _html(_run(history=history))
    assert "Flagged for attorney review" in html and "PII masking is on" in html


def test_quotes_with_line_breaks_render_as_one_block():
    from ui.findings import ledger_html
    html = ledger_html([{"sourceType": "document", "sourceId": "s", "location": "page 1",
                         "quote": "The\nresiduary\n\nbeneficiary   is\n\nCasey"},
                        {"sourceType": "account", "sourceId": "A", "field": "state", "value": "GA"}])
    assert "The residuary beneficiary is Casey" in html and "\n" not in html.split('role="note">')[1].split("</div>")[0]


def test_system_details_hidden_by_default_and_shown_with_toggle():
    hidden = _html(_run(status="review_needed", result=copy.deepcopy(LIVE)))
    assert "System details" not in hidden and "Est. cost" not in hidden and "Storage:" not in hidden
    shown = _html(_run(status="review_needed", result=copy.deepcopy(LIVE), show_details=True))
    assert "System details" in shown and "Storage:" in shown and "Est. cost" in shown


def test_aws_fallback_warnings_use_advisor_wording():
    result = copy.deepcopy(LIVE) | {"warnings": ["DynamoDB unavailable; using local JSON storage (AccessDenied)."]}
    hidden = _html(_run(status="review_needed", result=result))
    import html as html_lib
    assert "Working offline: decisions aren't being saved to the firm record." in html_lib.unescape(hidden)
    assert "AccessDenied" not in hidden  # technical detail only in System details
    shown = _html(_run(status="review_needed", result=result, show_details=True))
    assert "AccessDenied" in shown


def test_privacy_label_replaces_pii_badge(monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_PII_MASKING", "1")
    html = _html(_run())
    assert "Personal information protected" in html and "PII masking on" not in html



# --------------------------------------------------------------------------- decisions and next steps

def _action(at, decision):
    return next(b for b in at.button if b.key and b.key.startswith(f"action_{decision}_"))


def _next_steps_sections(at):
    """Text of each Next steps section, keyed by heading."""
    html = _html(at)
    heads = ["Follow up with the client", "For the client's attorney", "Dismissed (documented)", "Still to review"]
    out = {}
    for i, head in enumerate(heads):
        start = html.find(head)
        end = html.find(heads[i + 1]) if i + 1 < len(heads) else len(html)
        out[head] = html[start:end] if start >= 0 else ""
    return out


def test_decisions_blocked_without_reviewer(tmp_path, monkeypatch):
    at = _run(status="review_needed", result=copy.deepcopy(LIVE))
    assert all(_action(at, d).disabled for d in ("confirmed", "dismissed", "attorney_review"))
    assert "Enter your name to record this decision." in _html(at)
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), reviewer="A")  # one character is not enough
    assert _action(at, "confirmed").disabled


def test_dismiss_requires_a_reason(tmp_path, monkeypatch):
    import core.store as store
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), reviewer="Alex Advisor")
    _action(at, "dismissed").click().run()
    assert not at.exception
    assert "Add a short reason before dismissing" in _html(at)
    assert at.session_state["clearlegacy_ui"]["workspaces"]["morgan"]["decisions"] == {}


def test_decisions_move_items_between_next_steps_lists(tmp_path, monkeypatch):
    import core.store as store
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), reviewer="Alex Advisor")
    # Default selection is the critical finding ("TOD differs ..."): flag it for the attorney.
    _action(at, "attorney_review").click().run()
    sections = _next_steps_sections(at)
    assert "TOD differs" in sections["For the client's attorney"]
    assert "Alex Advisor" in sections["For the client's attorney"]
    # Dismiss the selected next item (the high POA finding) with a reason.
    note = next(t for t in at.text_area if t.key and t.key.startswith("review_note_") and "F-high" in t.key)
    note.input("Agent replaced by a new POA last year").run()
    _action(at, "dismissed").click().run()
    sections = _next_steps_sections(at)
    assert "POA agent marked deceased" in sections["Dismissed (documented)"]
    assert "Agent replaced by a new POA last year" in sections["Dismissed (documented)"]
    # Confirm the remaining review finding.
    _action(at, "confirmed").click().run()
    sections = _next_steps_sections(at)
    assert "governed by FL" in sections["Follow up with the client"]
    assert "Every item has a decision." in sections["Still to review"]
    ws = at.session_state["clearlegacy_ui"]["workspaces"]["morgan"]
    assert len(ws["decisions"]) == 3 and all(d["reviewer"] == "Alex Advisor" for d in ws["decisions"].values())
    # Review history shows the reviewer.
    assert _html(at).count("Alex Advisor") >= 3


def test_change_decision_moves_item_back(tmp_path, monkeypatch):
    import core.store as store
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), reviewer="Alex Advisor")
    _action(at, "attorney_review").click().run()  # flag the critical finding
    critical = next(b for b in at.button if b.key and b.key.startswith("pick") and "**Critical**" in b.label)
    critical.click().run()
    assert "Flagged" in next(b for b in at.button if b.key and b.key.startswith("pick") and "**Critical**" in b.label).label
    _action(at, "confirmed").click().run()  # Change decision -> Confirm
    sections = _next_steps_sections(at)
    assert "TOD differs" in sections["Follow up with the client"]
    assert "TOD differs" not in sections["For the client's attorney"]


def test_downloads_contain_the_right_findings_and_reviewer():
    from ui.next_steps import FOOTER, build_summary_html
    flagged = LIVE["findings"][1]
    confirmed = LIVE["findings"][0]
    decision = {"decision": "attorney_review", "note": "Call <b>attorney</b>", "reviewer": "Alex Advisor",
                "timestamp": "2026-10-03T07:00"}
    groups = {"attorney_review": [(flagged, decision)],
              "confirmed": [(confirmed, decision | {"decision": "confirmed"})], "dismissed": [], "open": []}
    attorney = build_summary_html("attorney", "Jordan Morgan", LIVE, groups, "Alex Advisor")
    client = build_summary_html("client", "Jordan Morgan", LIVE, groups, "Alex Advisor")
    assert "Prepared by ClearLegacy for review with the client&#x27;s attorney" in attorney
    assert "TOD differs" in attorney and "governed by FL" not in attorney
    assert "morgan_will_summary.pdf" in attorney and "Avery Morgan" in attorney
    assert "Alex Advisor" in attorney and "Alex Advisor" in client
    assert "governed by FL" in client and "Confirm with the client." in client
    assert FOOTER in attorney and FOOTER in client
    assert XSS not in attorney and "&lt;script&gt;" in attorney and "<b>attorney</b>" not in attorney


def test_download_buttons_render_on_next_steps(tmp_path, monkeypatch):
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), reviewer="Alex Advisor")
    labels = [e.proto.label for e in at.get("download_button")]
    assert "Download attorney review summary" in labels and "Download client follow-up list" in labels

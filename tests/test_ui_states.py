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


def _run(selected="morgan", **workspace_kwargs):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["clearlegacy_ui"] = {"selected_client_id": selected,
                                          "workspaces": {selected: _workspace(**workspace_kwargs)}}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _html(at):
    return "\n".join(str(m.value) for m in at.markdown)


@pytest.mark.parametrize("household", ["morgan", "patel", "rivera"])
def test_empty_state_each_household(household):
    at = _run(selected=household)
    assert "No analysis yet" in _html(at)
    assert [t.label for t in at.tabs] == ["Findings", "Ask ClearLegacy", "Review history"]


def test_live_result_renders_sorted_findings_ledger_and_footer():
    decided = {"analysis-test:F-high": {"analysisId": "analysis-test", "findingId": "F-high", "decision": "confirmed",
                                        "note": "Spoke with client", "reviewer": "Advisor", "timestamp": "2026-10-02T20:00"}}
    at = _run(status="review_needed", result=copy.deepcopy(LIVE), decisions=decided)
    html = _html(at)
    assert html.index("TOD differs") < html.index("POA agent") < html.index("governed by FL")  # critical, high, review
    assert "Document says" in html and "Account record says" in html and "≠" in html
    assert "Avery Morgan" in html and "50%" in html  # account JSON shown as readable rows
    assert "1 of 3" in html  # decisions tile
    assert "Confirmed" in html and "Est. cost" in html and "Claude Sonnet 5" in html
    assert XSS not in html and "&lt;script&gt;" in html  # untrusted text is escaped
    assert any(c.label.startswith("No successor agent") for c in at.checkbox)


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

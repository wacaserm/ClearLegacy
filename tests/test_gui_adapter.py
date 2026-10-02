"""GUI adapter wiring to the pipeline and assistant. No AWS or Streamlit server needed."""

import types

import services.gui_adapter as adapter

SOURCE = "sha256-abc123"
UPLOADS = [{"filename": "planning_summary.pdf", "file_bytes": b"%PDF-1", "category": "planning"}]
PREVIEWS = [{"sourceId": SOURCE, "filename": "planning_summary.pdf", "sections": []}]
FINDING = {
    "findingId": "F1", "priority": "high", "title": "Mismatch",
    "evidence": [
        {"sourceType": "document", "sourceId": SOURCE, "location": "page 1", "quote": "I want Casey Morgan"},
        {"sourceType": "account", "sourceId": "DEMO-MORGAN-IRA", "field": "primaryBeneficiaries", "value": "Taylor"},
    ],
}


def _backend(analyze):
    return {"pipeline": types.SimpleNamespace(analyze=analyze), "reader": None, "store": None, "errors": {}}


def test_analyze_sends_raw_uploads_and_labels_sources():
    calls = []

    def analyze(client_id, documents):
        calls.append((client_id, documents))
        return {"status": "review_needed", "findings": [dict(FINDING, evidence=[dict(e) for e in FINDING["evidence"]])],
                "clarificationQuestions": [f"Clarify information from {SOURCE}: x"], "warnings": []}

    result = adapter.analyze_documents("morgan", UPLOADS, _backend(analyze), PREVIEWS)
    assert calls == [("morgan", [(b"%PDF-1", "planning_summary.pdf")])]
    assert result["findings"][0]["evidence"][0]["filename"] == "planning_summary.pdf"
    assert "filename" not in result["findings"][0]["evidence"][1]
    assert result["clarificationQuestions"] == ["Clarify information from planning_summary.pdf: x"]
    assert result["sourceNames"] == {SOURCE: "planning_summary.pdf"}


def test_ask_question_uses_finding_quotes_when_facts_missing(monkeypatch):
    seen = {}

    def fake_answer(question, facts_list, client, accounts, findings, history):
        seen.update(facts_list=facts_list, findings=findings)
        return {"answer": "ok", "canAnswer": True, "citations": [], "droppedCitations": 0}

    import core.assistant
    monkeypatch.setattr(core.assistant, "answer_question", fake_answer)
    adapter.ask_question("Why?", {"clientId": "morgan"}, [], {"findings": [FINDING]}, [])
    assert seen["facts_list"] == [{"sourceId": SOURCE, "docType": None, "facts": [
        {"field": "evidence", "value": "I want Casey Morgan", "location": "page 1", "quote": "I want Casey Morgan"}]}]


def test_ask_question_prefers_pipeline_facts(monkeypatch):
    import core.assistant
    monkeypatch.setattr(core.assistant, "answer_question", lambda q, facts_list, *a: {"facts": facts_list})
    facts = [{"sourceId": "s", "facts": []}]
    assert adapter.ask_question("q", {}, [], {"facts": facts, "findings": [FINDING]}, [])["facts"] is facts


def test_summary_is_optional(monkeypatch):
    import core.explain

    def boom(*a):
        raise RuntimeError("Bedrock down")

    monkeypatch.setattr(core.explain, "summarize_case", boom)
    assert adapter.summarize({}, [FINDING]) is None
    assert adapter.summarize({}, []) is None


def test_ask_question_quotes_document_text_when_available(monkeypatch):
    import core.assistant
    monkeypatch.setattr(core.assistant, "answer_question", lambda q, facts_list, *a: {"facts": facts_list})
    analysis = {"findings": [FINDING], "documents": [
        {"sourceId": SOURCE, "filename": "planning_summary.pdf", "docType": "planning_summary",
         "sections": [{"location": "page 1", "text": "For brokerage, Avery and Riley at 50% each."}]}]}
    facts = adapter.ask_question("q", {}, [], analysis, [])["facts"]
    assert facts[0]["facts"][0]["quote"] == "For brokerage, Avery and Riley at 50% each."
    assert facts[0]["facts"][0]["location"] == "page 1"


def test_analyze_keeps_read_text_for_qa():
    result = adapter.analyze_documents("morgan", UPLOADS, _backend(lambda c, d: {"status": "review_needed", "findings": []}),
                                       [dict(PREVIEWS[0], sections=[{"location": "page 1", "text": "hi"}])])
    assert result["documents"][0]["sections"] == [{"location": "page 1", "text": "hi"}]

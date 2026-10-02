"""Malformed model output, truncation, fallbacks, and the read-only assistant. Model is mocked."""

import pytest

import core.assistant as assistant_mod
import core.bedrock_client as bc
import core.explain as explain_mod
import core.extract as extract_mod

DOC = {"sourceId": "d1", "filename": "d1.pdf", "docType": None,
       "sections": [{"location": "page 1", "text": "I appoint my brother, Thomas Johnson, as Executor."}]}
GOOD = {"field": "executor", "value": "Thomas Johnson", "location": "page 1",
        "quote": "my brother, Thomas Johnson, as Executor"}


def test_malformed_facts_become_warnings(monkeypatch):
    raw = {"docType": "spaceship", "facts": [
        GOOD,
        {"field": "favorite_color", "value": "blue", "location": "page 1", "quote": "x"},
        {"field": "executor", "value": "Thomas Johnson", "location": "page 1"},  # no quote
        "not a dict",
        {**GOOD, "tier": "tertiary", "allocation": "  "},
    ]}
    monkeypatch.setattr(extract_mod, "call_tool", lambda **kw: raw)
    out = extract_mod.extract_facts(DOC)
    assert out["docType"] == "other"
    assert len(out["facts"]) == 2
    assert out["facts"][1]["tier"] is None and out["facts"][1]["allocation"] is None
    assert set(out["facts"][0]) == {"field", "value", "location", "quote",
                                    "accountRef", "tier", "allocation", "relationship", "asOf"}
    assert [w["code"] for w in out["warnings"]] == ["malformed_fact"] * 3


def test_missing_fact_list_is_flagged(monkeypatch):
    monkeypatch.setattr(extract_mod, "call_tool", lambda **kw: {"docType": "will"})
    out = extract_mod.extract_facts(DOC)
    assert out["facts"] == [] and out["warnings"][0]["code"] == "malformed_output"


class _FakeClient:
    def __init__(self, response):
        self.response = response

    def converse(self, **kwargs):
        assert "temperature" not in kwargs["inferenceConfig"]
        return self.response


def _call(monkeypatch, response):
    monkeypatch.setattr(bc, "get_client", lambda service="bedrock-runtime": _FakeClient(response))
    return bc.call_tool("sys", "user", "t", "desc", {"type": "object"})


def test_truncated_output_is_rejected(monkeypatch):
    resp = {"stopReason": "max_tokens", "output": {"message": {"content": [
        {"toolUse": {"name": "t", "input": {"facts": []}}}]}}}
    with pytest.raises(bc.BedrockError, match="maxTokens"):
        _call(monkeypatch, resp)


def test_string_tool_input_is_parsed_and_garbage_rejected(monkeypatch):
    ok = {"stopReason": "tool_use", "output": {"message": {"content": [
        {"toolUse": {"name": "t", "input": '{"a": 1}'}}]}}}
    assert _call(monkeypatch, ok) == {"a": 1}
    bad = {"stopReason": "tool_use", "output": {"message": {"content": [
        {"toolUse": {"name": "t", "input": "not json"}}]}}}
    with pytest.raises(bc.BedrockError, match="malformed"):
        _call(monkeypatch, bad)


def test_explain_trims_and_falls_back(monkeypatch):
    monkeypatch.setattr(explain_mod, "call_tool", lambda **kw: {
        "explanation": "One. Two. Three.", "recommendedAction": ""})
    out = explain_mod.explain({"findingId": "F1", "title": "T", "evidence": []})
    assert out["explanation"] == "One. Two."
    assert out["recommendedAction"] == explain_mod.DEFAULT_ACTION


def test_summary_without_findings_skips_model(monkeypatch):
    monkeypatch.setattr(explain_mod, "call_tool", lambda **kw: pytest.fail("model should not be called"))
    assert explain_mod.summarize_case({"name": "X"}, [])["summary"] == explain_mod.NO_FINDINGS_SUMMARY


FACTS = [{"sourceId": "d1", "docType": "will", "facts": [GOOD], "warnings": []}]
CLIENT = {"clientId": "C", "profileNotes": ["Thomas Johnson deceased, March 2025"]}


def _ev_doc(quote):
    return {"sourceType": "document", "sourceId": "d1", "location": "page 1", "quote": quote, "field": None, "value": None}


def test_assistant_keeps_verified_citations(monkeypatch):
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: {
        "canAnswer": True, "answer": "Thomas Johnson is the executor.",
        "citations": [_ev_doc("Thomas Johnson, as Executor"), _ev_doc("made-up text")]})
    out = assistant_mod.answer_question("Who is executor?", FACTS, CLIENT, [])
    assert out["canAnswer"] and len(out["citations"]) == 1 and out["droppedCitations"] == 1


def test_assistant_withholds_unsupported_answer(monkeypatch):
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: {
        "canAnswer": True, "answer": "Linda gets everything.", "citations": [_ev_doc("Linda gets everything")]})
    out = assistant_mod.answer_question("Who inherits?", FACTS, CLIENT, [])
    assert out["answer"] == assistant_mod.UNSUPPORTED_ANSWER and not out["canAnswer"]


def test_assistant_strips_leaked_markup_and_infers_can_answer(monkeypatch):
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: {
        "answer": 'Thomas Johnson is the executor.</answer>\n<parameter name="canAnswer">true',
        "citations": [_ev_doc("Thomas Johnson, as Executor")]})
    out = assistant_mod.answer_question("Who is executor?", FACTS, CLIENT, [])
    assert out["answer"] == "Thomas Johnson is the executor." and out["canAnswer"] is True

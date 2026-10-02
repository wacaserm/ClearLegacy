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
    assert len(out["warnings"]) == 3 and all("Skipped malformed fact" in w for w in out["warnings"])


def test_missing_fact_list_is_flagged(monkeypatch):
    monkeypatch.setattr(extract_mod, "call_tool", lambda **kw: {"docType": "will"})
    out = extract_mod.extract_facts(DOC)
    assert out["facts"] == [] and "no fact list" in out["warnings"][0]


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
    finding = {"findingId": "F1", "priority": "high", "title": "T", "evidence": [{"sourceType": "document"}]}
    out = explain_mod.explain(finding)
    # The pipeline replaces each finding with explain()'s result, so nothing may be lost.
    assert {k: out[k] for k in finding} == finding
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


def test_assistant_withholds_uncited_answer_when_can_answer_missing(monkeypatch):
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: {
        "answer": "Taylor Morgan is the beneficiary.</answer><parameter name=\"citations\">[...]", "citations": []})
    out = assistant_mod.answer_question("Who?", FACTS, CLIENT, [])
    assert out["answer"] == assistant_mod.UNSUPPORTED_ANSWER and out["citations"] == []


def test_assistant_shows_explicit_cannot_answer():
    import core.assistant as a
    a_call = a.call_tool
    try:
        a.call_tool = lambda **kw: {"citations": [], "canAnswer": False, "answer": "The records don't include an SSN."}
        out = a.answer_question("SSN?", FACTS, CLIENT, [])
    finally:
        a.call_tool = a_call
    assert out == {"answer": "The records don't include an SSN.", "canAnswer": False, "citations": [], "droppedCitations": 0}


def test_missing_credentials_message_differs_from_expired(monkeypatch):
    from botocore.exceptions import NoCredentialsError

    class _NoCreds:
        def converse(self, **kw):
            raise NoCredentialsError()

    monkeypatch.setattr(bc, "get_client", lambda service="bedrock-runtime": _NoCreds())
    with pytest.raises(bc.AWSCredentialsExpired) as info:  # still catchable as before
        bc.call_tool("s", "u", "t", "d", {"type": "object"})
    assert isinstance(info.value, bc.AWSCredentialsMissing) and "not found" in str(info.value)


def test_unavailable_model_names_the_setting(monkeypatch):
    from botocore.exceptions import ClientError

    class _BadModel:
        def converse(self, **kw):
            raise ClientError({"Error": {"Code": "ValidationException",
                                         "Message": "The provided model identifier is invalid."}}, "Converse")

    monkeypatch.setattr(bc, "get_client", lambda service="bedrock-runtime": _BadModel())
    with pytest.raises(bc.BedrockError, match="CLEARLEGACY_MODEL_ID"):
        bc.call_tool("s", "u", "t", "d", {"type": "object"})


def test_assistant_retries_once_when_citations_are_lost(monkeypatch):
    replies = iter([
        {"answer": "Thomas Johnson is the executor.", "citations": []},  # citations lost
        {"citations": [_ev_doc("Thomas Johnson, as Executor")], "canAnswer": True, "answer": "Thomas Johnson is the executor."},
    ])
    calls = []
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: calls.append(1) or next(replies))
    out = assistant_mod.answer_question("Who?", FACTS, CLIENT, [])
    assert len(calls) == 2 and out["canAnswer"] and len(out["citations"]) == 1


def test_assistant_gives_up_after_one_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(assistant_mod, "call_tool", lambda **kw: calls.append(1) or {"answer": "Uncited claim.", "citations": []})
    out = assistant_mod.answer_question("Who?", FACTS, CLIENT, [])
    assert len(calls) == 2 and out["answer"] == assistant_mod.UNSUPPORTED_ANSWER


def test_usage_is_recorded_and_priced(monkeypatch):
    resp = {"stopReason": "tool_use", "usage": {"inputTokens": 1_000_000, "outputTokens": 100_000},
            "output": {"message": {"content": [{"toolUse": {"name": "t", "input": {"ok": True}}}]}}}
    monkeypatch.setattr(bc, "get_client", lambda service="bedrock-runtime": _FakeClient(resp))
    before = bc.usage_snapshot()
    bc.call_tool("s", "u", "t", "d", {"type": "object"}, model_id="us.anthropic.claude-sonnet-5")
    bc.call_tool("s", "u", "t", "d", {"type": "object"}, model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    usage = bc.usage_since(before)
    assert usage["models"]["us.anthropic.claude-sonnet-5"] == {"calls": 1, "inputTokens": 1_000_000,
                                                               "outputTokens": 100_000, "estimatedCostUSD": 3.0}
    assert usage["estimatedCostUSD"] == 3.0 + 1.5  # Sonnet 2+1, Haiku 1+0.5

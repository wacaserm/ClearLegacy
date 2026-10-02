"""find_additional_conflicts drops AI findings whose evidence doesn't verify. Model is mocked."""

import core.explain as explain_mod
from core.extract import extract_facts

WILL = {
    "sourceId": "johnson-will",
    "docType": "will",
    "facts": [
        {"field": "executor", "value": "Thomas Johnson", "location": "page 2",
         "quote": "I nominate and appoint my brother, Thomas Johnson, as Executor"},
    ],
    "warnings": [],
}
CLIENT = {"clientId": "DEMO-JOHNSON", "profileNotes": ["Thomas Johnson deceased, March 2025"]}
ACCOUNTS = [{"accountId": "DEMO-JOHNSON-4471", "registration": "Individual Robert Johnson"}]


def _doc_ev(quote, location="page 1", source="johnson-will"):
    return {"sourceType": "document", "sourceId": source, "location": location, "quote": quote, "field": None, "value": None}


def _acct_ev(source, field, value):
    return {"sourceType": "account", "sourceId": source, "location": None, "quote": None, "field": field, "value": value}


def test_unverified_findings_are_dropped(monkeypatch):
    fake = {"findings": [
        {"title": "Executor reported deceased", "evidence": [
            _doc_ev("my brother, Thomas Johnson, as Executor"),
            _acct_ev("DEMO-JOHNSON", "profileNotes", "Thomas Johnson deceased, March 2025"),
        ]},
        {"title": "Invented document quote", "evidence": [_doc_ev("I leave my boat to Linda")]},
        {"title": "Wrong account field", "evidence": [_acct_ev("DEMO-JOHNSON-4471", "registration", "Trust")]},
        {"title": "Unknown account", "evidence": [_acct_ev("DEMO-OTHER-1", "registration", "Individual")]},
    ]}
    monkeypatch.setattr(explain_mod, "call_tool", lambda **kw: fake)
    out = explain_mod.find_additional_conflicts([WILL], CLIENT, ACCOUNTS)
    assert len(out) == 1
    f = out[0]
    assert f["findingId"] == "AI-1" and f["priority"] == "review"
    assert f["evidence"][0] == {"sourceType": "document", "sourceId": "johnson-will",
                                "location": "page 2", "quote": "my brother, Thomas Johnson, as Executor"}
    assert f["evidence"][1] == {"sourceType": "account", "sourceId": "DEMO-JOHNSON",
                                "field": "profileNotes", "value": "Thomas Johnson deceased, March 2025"}


def test_empty_document_returns_warning_without_model_call():
    out = extract_facts({"sourceId": "blank", "filename": "blank.pdf", "docType": "will",
                         "sections": [{"location": "page 1", "text": "  "}]})
    assert out["facts"] == []
    assert "No readable text" in out["warnings"][0]


def test_combined_and_dotted_account_values():
    client = {"clientId": "C", "trustedContact": {"name": "Thomas Johnson"}}
    accounts = [{"accountId": "A", "todBeneficiaries": [
        {"name": "Linda Johnson", "relationship": "former spouse", "tier": "primary",
         "allocation": "100%", "recordedDate": "2009-05-11"}]}]
    v = explain_mod.verify_account_evidence
    assert v(_acct_ev("C", "trustedContact.name", "Thomas Johnson"), client, accounts)
    assert v(_acct_ev("A", "todBeneficiaries",
                      "Linda Johnson, former spouse, primary, 100%, recordedDate 2009-05-11"), client, accounts)
    assert not v(_acct_ev("A", "todBeneficiaries", "Linda Johnson, 50%"), client, accounts)
    assert not v(_acct_ev("C", "trustedContact.phone", "555"), client, accounts)


def test_labeled_value_needs_exact_match():
    accounts = [{"accountId": "A", "todBeneficiaries": [{"name": "Linda Johnson", "recordedDate": "2009-05-11"}]}]
    v = explain_mod.verify_account_evidence
    assert v(_acct_ev("A", "todBeneficiaries", "Linda Johnson, recorded 2009-05-11"), {}, accounts)
    assert not v(_acct_ev("A", "todBeneficiaries", "Linda Johnson, recorded 2010-01-01"), {}, accounts)
    assert not v(_acct_ev("A", "todBeneficiaries", "Linda Johnson, former spouse Carol"), {}, accounts)


def test_numeric_percentages_in_team_record_format():
    client = {"clientId": "morgan", "formerSpouse": "Taylor Morgan"}
    accounts = [{"accountId": "DEMO-MORGAN-IRA", "primaryBeneficiaries": [
        {"name": "Taylor Morgan", "relationship": "former spouse", "percentage": 100}]}]
    v = explain_mod.verify_account_evidence
    assert v(_acct_ev("DEMO-MORGAN-IRA", "primaryBeneficiaries", "Taylor Morgan, former spouse, 100%"), client, accounts)
    assert not v(_acct_ev("DEMO-MORGAN-IRA", "primaryBeneficiaries", "Taylor Morgan, 50%"), client, accounts)
    assert v(_acct_ev("morgan", "formerSpouse", "Taylor Morgan"), client, accounts)

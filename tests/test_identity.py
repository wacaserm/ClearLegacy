"""Wrong-client safety check: name matcher, account check, and the pipeline stop."""

import pytest

from core import identity, pipeline

MORGAN = {"clientId": "morgan", "name": "Jordan Morgan", "currentSpouse": "Casey Morgan",
          "formerSpouse": "Taylor Morgan", "trustName": "Morgan Family Trust"}
MORGAN_ACCOUNTS = [{"accountId": "DEMO-MORGAN-IRA"}, {"accountId": "DEMO-MORGAN-BROKERAGE"}]
PATEL_ACCOUNTS = {"DEMO-PATEL-IRA", "DEMO-PATEL-BROKERAGE"}


def _doc(*facts):
    return {"sourceId": "d1", "docType": "will", "facts": [dict(f) for f in facts]}


def _name(value):
    return {"field": "client_name", "value": value}


def _check(*facts, name="will.pdf"):
    return identity.check_identity([(name, _doc(*facts))], MORGAN, MORGAN_ACCOUNTS, PATEL_ACCOUNTS)


@pytest.mark.parametrize("value", ["Jordan Morgan", "jordan morgan", "Jordan A. Morgan", "Jordan Alex Morgan",
                                   "Mr. Jordan Morgan Jr.", "Jordan Morgan, Sr."])
def test_client_name_matches_after_normalizing(value):
    assert identity.classify_name(value, MORGAN) == "match"
    assert _check(_name(value)) == {"mismatches": [], "warnings": []}


def test_spouse_on_a_joint_will_passes():
    assert identity.classify_name("Casey Morgan", MORGAN) == "match"
    assert identity.classify_name("Jordan and Casey Morgan", MORGAN) == "match"
    assert identity.classify_name("Jordan Morgan & Casey Morgan", MORGAN) == "match"


def test_children_agents_and_trust_in_other_fields_do_not_block():
    result = _check(_name("Jordan Morgan"),
                    {"field": "family_member", "value": "Avery Morgan"},
                    {"field": "poa_agent", "value": "Pat Morgan"},
                    {"field": "successor_trustee", "value": "Sam Patel"},
                    {"field": "trust_owned_account", "value": "Morgan Family Trust", "accountRef": "DEMO-MORGAN-BROKERAGE"})
    assert result == {"mismatches": [], "warnings": []}
    assert identity.classify_name("Morgan Family Trust", MORGAN) == "match"


def test_a_different_client_fails():
    assert identity.classify_name("Sam Patel", MORGAN) == "mismatch"
    result = _check(_name("Sam Patel"), name="planning_summary.pdf")
    assert result["mismatches"] == [{"fileName": "planning_summary.pdf", "nameFound": "Sam Patel",
                                     "expectedName": "Jordan Morgan"}]


def test_missing_or_uncertain_name_only_warns():
    assert _check({"field": "residuary_beneficiary", "value": "Casey Morgan"}) == {
        "mismatches": [], "warnings": ["Couldn't confirm the client name on will.pdf; please verify."]}
    for value in ("Jordan", "Jim Morgan", "Patel Family Trust"):  # single word, nickname, unknown trust
        result = _check(_name(value))
        assert result["mismatches"] == [] and len(result["warnings"]) == 1, value


def test_former_spouse_is_not_a_principal():
    assert identity.classify_name("Taylor Morgan", MORGAN) == "unclear"  # same surname: warn, never pass silently


def test_account_on_file_for_another_household_is_a_mismatch():
    result = _check({"field": "intended_beneficiary", "value": "Lee Patel", "accountRef": "DEMO-PATEL-IRA"})
    assert result["mismatches"][0]["accountRefs"] == ["DEMO-PATEL-IRA"]
    # An account that isn't on file anywhere (outside account) does not block.
    outside = _check(_name("Jordan Morgan"), {"field": "intended_beneficiary", "value": "Avery", "accountRef": "account ending 4471"})
    assert outside["mismatches"] == []


def _stub_pipeline(monkeypatch, facts):
    calls = []

    def fake(name):
        def run(*args, **kwargs):
            calls.append(name)
            return {"extract_facts": lambda d: facts, "validate_facts": lambda f, d: f,
                    "reconcile": lambda *a: {"status": "review_needed", "findings": [{"findingId": "F1"}],
                                             "clarificationQuestions": ["Q?"]},
                    "explain": lambda f: f}[name](*args, **kwargs)
        return run

    monkeypatch.setattr(pipeline, "_load_function", lambda module, function: (fake(function), None))
    monkeypatch.setattr(pipeline.store, "get_client", lambda cid: MORGAN)
    monkeypatch.setattr(pipeline.store, "get_accounts",
                        lambda cid: MORGAN_ACCOUNTS if cid == "morgan" else [{"accountId": a} for a in sorted(PATEL_ACCOUNTS)])
    monkeypatch.setattr(pipeline.store, "get_clients", lambda: [{"clientId": "morgan"}, {"clientId": "patel"}])
    saved = []
    monkeypatch.setattr(pipeline.store, "save_findings", lambda *a: saved.append(a))
    return calls, saved


def test_pipeline_stops_on_mismatch_without_rules_or_saving(monkeypatch):
    calls, saved = _stub_pipeline(monkeypatch, _doc(_name("Sam Patel")))
    result = pipeline._analyze("morgan", [{"filename": "planning_summary.pdf", "status": "ok", "sections": []}])
    assert result["status"] == "client_mismatch"
    assert result["clientMismatch"][0]["nameFound"] == "Sam Patel"
    assert result["findings"] == [] and result["clarificationQuestions"] == []
    assert "reconcile" not in calls and "explain" not in calls and saved == []


def test_pipeline_continues_for_the_right_client(monkeypatch):
    calls, saved = _stub_pipeline(monkeypatch, _doc(_name("Jordan A. Morgan")))
    result = pipeline._analyze("morgan", [{"filename": "will.pdf", "status": "ok", "sections": []}])
    assert result["status"] == "review_needed" and "reconcile" in calls and len(saved) == 1


def test_quarantine_deletes_the_uploaded_version(monkeypatch):
    deleted = []

    class S3:
        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    monkeypatch.setattr("core.bedrock_client.get_client", lambda name: S3())
    pipeline._quarantine_uploads([{"filename": "p.pdf", "s3Bucket": "b", "s3Key": "clients/morgan/p.pdf", "s3VersionId": "v1"},
                                  {"filename": "ok.pdf", "s3Bucket": "b", "s3Key": "clients/morgan/ok.pdf", "s3VersionId": "v2"}],
                                 {"p.pdf"})
    assert deleted == [{"Bucket": "b", "Key": "clients/morgan/p.pdf", "VersionId": "v1"}]

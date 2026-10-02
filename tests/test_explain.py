"""find_additional_conflicts drops AI findings whose evidence doesn't verify. Model is mocked."""

import core.explain as explain_mod

WILL = {
    "docType": "will",
    "dateSigned": {"value": "2019-03-14", "page": 2, "quote": "I have signed this Will on March 14, 2019"},
    "governingState": {"value": None, "page": None, "quote": None},
    "people": [
        {"name": "Thomas Johnson", "relationship": "brother", "role": "executor", "share": None,
         "page": 2, "quote": "I nominate and appoint my brother, Thomas Johnson, as Executor"},
    ],
    "assets": [],
}
CLIENT = {"name": "Robert Johnson", "profileNotes": ["Thomas Johnson deceased, March 2025"]}
ACCOUNTS = [{"accountId": "...4471", "registration": "Individual"}]


def test_unverified_findings_are_dropped(monkeypatch):
    fake = {"findings": [
        {"title": "Executor is deceased", "evidence": [
            {"source": "document", "docType": "will", "page": 1, "quote": "my brother, Thomas Johnson, as Executor"},
            {"source": "account", "docType": None, "page": None, "quote": "Thomas Johnson deceased, March 2025"},
        ]},
        {"title": "Invented conflict", "evidence": [
            {"source": "document", "docType": "will", "page": 1, "quote": "I leave my boat to Linda"},
        ]},
    ]}
    monkeypatch.setattr(explain_mod, "call_tool", lambda **kw: fake)
    out = explain_mod.find_additional_conflicts([WILL], CLIENT, ACCOUNTS)
    assert len(out) == 1
    f = out[0]
    assert f["findingId"] == "AI-1" and f["severity"] == "review"
    assert f["evidence"][0]["page"] == 2  # corrected from 1

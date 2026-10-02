"""Tests for rules 1 (will/trust vs TOD, Critical), 2, 3 and 4.

Facts use the real extractor vocabulary (core/extract.py FACT_FIELDS):
residuary_beneficiary, trust_owned_account, poa_agent / trustee / executor,
governing_state (two-letter state code).
The original beneficiary tests stay in test_rules.py.
"""

import json
from copy import deepcopy
from pathlib import Path

from core.rules import reconcile


ROOT = Path(__file__).resolve().parents[1]


def load_client(client_id):
    with open(ROOT / "data" / "clients.json", encoding="utf-8") as file:
        clients = json.load(file)["clients"]
    return next(c for c in clients if c["clientId"] == client_id)


def fact(field, value, quote, account=None, tier=None, allocation=None):
    return {
        "field": field,
        "value": value,
        "location": "page 1",
        "quote": quote,
        "accountRef": account,
        "tier": tier,
        "allocation": allocation,
        "relationship": None,
        "asOf": None,
    }


def document(source_id, facts, doc_type="planning_summary"):
    return {
        "sourceId": source_id,
        "docType": doc_type,
        "facts": facts,
        "warnings": [],
    }


def priorities(result):
    return [f["priority"] for f in result["findings"]]


def evidence_types(finding):
    return {e["sourceType"] for e in finding["evidence"]}


# ------------------------------------------- Rule 1: will/trust vs TOD

def will_names(*names, doc_type="will"):
    facts = [
        fact("residuary_beneficiary", name,
             f"I leave the rest of my estate to {name}.")
        for name in names
    ]
    return [document("MORGAN-WILL-2019", facts, doc_type)]


def test_tod_beneficiary_not_in_will_is_critical():
    client = load_client("morgan")  # brokerage TOD: Avery and Riley

    result = reconcile(will_names("Casey Morgan"), client, client["accounts"])

    assert result["status"] == "review_needed"
    assert priorities(result) == ["critical"]
    finding = result["findings"][0]
    assert "Avery Morgan" in finding["explanation"]
    assert "Riley Morgan" in finding["explanation"]
    assert evidence_types(finding) == {"document", "account"}
    account_evidence = next(
        e for e in finding["evidence"] if e["sourceType"] == "account"
    )
    assert account_evidence["sourceId"] == "DEMO-MORGAN-BROKERAGE"


def test_only_the_unnamed_tod_beneficiary_is_reported():
    client = load_client("morgan")

    result = reconcile(
        will_names("Avery Morgan"), client, client["accounts"]
    )

    assert priorities(result) == ["critical"]
    explanation = result["findings"][0]["explanation"]
    assert "Riley Morgan" in explanation
    assert "Avery Morgan" not in explanation


def test_trust_counts_as_a_legal_document():
    client = load_client("morgan")

    result = reconcile(
        will_names("Casey Morgan", doc_type="trust"),
        client, client["accounts"],
    )

    assert priorities(result) == ["critical"]


def test_tod_beneficiaries_all_named_in_will_is_clean():
    client = load_client("morgan")

    result = reconcile(
        will_names("Avery Morgan", "Riley Morgan"),
        client, client["accounts"],
    )

    assert result["status"] == "no_discrepancies_found"
    assert result["findings"] == []


def test_planning_summary_is_not_treated_as_a_will():
    client = load_client("morgan")

    result = reconcile(
        will_names("Casey Morgan", doc_type="planning_summary"),
        client, client["accounts"],
    )

    assert "critical" not in priorities(result)


# ------------------------------------------------ Rule 2: trust funding

TRUST_QUOTE = (
    "The Morgan Family Trust holds brokerage account "
    "DEMO-MORGAN-BROKERAGE."
)


def trust_doc():
    return [document("MORGAN-TRUST-2021", [
        fact("trust_owned_account", "Morgan Family Trust", TRUST_QUOTE,
             "DEMO-MORGAN-BROKERAGE"),
    ], "trust")]


def test_unfunded_trust_is_high():
    client = load_client("morgan")  # brokerage registered as individual

    result = reconcile(trust_doc(), client, client["accounts"])

    assert result["status"] == "review_needed"
    assert priorities(result) == ["high"]
    finding = result["findings"][0]
    assert evidence_types(finding) == {"document", "account"}
    account_evidence = next(
        e for e in finding["evidence"] if e["sourceType"] == "account"
    )
    assert account_evidence["field"] == "registration"
    assert account_evidence["value"] == "Jordan Morgan, individual"


def test_funded_trust_is_clean():
    client = load_client("morgan")
    accounts = deepcopy(client["accounts"])
    brokerage = next(
        a for a in accounts if a["accountId"] == "DEMO-MORGAN-BROKERAGE"
    )
    brokerage["registration"] = (
        "Jordan Morgan, Trustee of the Morgan Family Trust"
    )

    result = reconcile(trust_doc(), client, accounts)

    assert result["status"] == "no_discrepancies_found"
    assert result["findings"] == []


def test_missing_registration_is_a_question_not_a_finding():
    client = load_client("morgan")
    accounts = deepcopy(client["accounts"])
    for account in accounts:
        account.pop("registration", None)

    result = reconcile(trust_doc(), client, accounts)

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert any(
        "registration" in q and "DEMO-MORGAN-BROKERAGE" in q
        for q in result["clarificationQuestions"]
    )


def test_missing_trust_name_is_a_question_not_a_finding():
    client = deepcopy(load_client("morgan"))
    client.pop("trustName")

    result = reconcile(trust_doc(), client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert any("trust" in q for q in result["clarificationQuestions"])


# -------------------------------------------- Rule 3: deceased fiduciary

def fiduciary_doc(field, name, doc_type="poa"):
    quote = f"I appoint {name} as my {field.replace('_', ' ')}."
    return [document("MORGAN-POA-2019", [fact(field, name, quote)], doc_type)]


def test_deceased_poa_agent_is_high():
    client = load_client("morgan")  # Pat Morgan is marked deceased

    result = reconcile(
        fiduciary_doc("poa_agent", "Pat Morgan"), client, client["accounts"]
    )

    assert result["status"] == "review_needed"
    assert priorities(result) == ["high"]
    finding = result["findings"][0]
    assert evidence_types(finding) == {"document", "account"}
    profile_evidence = next(
        e for e in finding["evidence"] if e["sourceType"] == "account"
    )
    assert profile_evidence["field"] == "fiduciaries"
    assert "deceased" in profile_evidence["value"]


def test_living_fiduciary_is_clean():
    client = load_client("morgan")

    result = reconcile(
        fiduciary_doc("executor", "Casey Morgan", "will"),
        client, client["accounts"],
    )

    assert result["status"] == "no_discrepancies_found"
    assert result["findings"] == []


def test_fiduciary_not_in_profile_is_a_question():
    client = load_client("morgan")

    result = reconcile(
        fiduciary_doc("trustee", "Dana Unknown", "trust"),
        client, client["accounts"],
    )

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert any("Dana Unknown" in q for q in result["clarificationQuestions"])


# ----------------------------------------------- Rule 4: governing state

def state_doc(state):
    quote = f"This document is governed by the laws of {state}."
    return [document("MORGAN-WILL-2019", [
        fact("governing_state", state, quote),
    ], "will")]


def test_governing_state_mismatch_is_review():
    client = load_client("morgan")  # lives in GA

    result = reconcile(state_doc("FL"), client, client["accounts"])

    assert result["status"] == "review_needed"
    assert priorities(result) == ["review"]
    assert evidence_types(result["findings"][0]) == {"document", "account"}


def test_matching_state_is_clean_and_case_insensitive():
    client = load_client("morgan")

    result = reconcile(state_doc("ga"), client, client["accounts"])

    assert result["status"] == "no_discrepancies_found"
    assert result["findings"] == []


def test_missing_client_state_is_a_question():
    client = deepcopy(load_client("morgan"))
    client.pop("state")

    result = reconcile(state_doc("FL"), client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert any("state" in q for q in result["clarificationQuestions"])


# ------------------------------------------------------------- Combined

def test_all_rules_together_and_ids_are_repeatable():
    client = load_client("morgan")
    docs = [
        document("MORGAN-WILL-2019", [
            fact("residuary_beneficiary", "Casey Morgan",
                 "I leave the rest of my estate to Casey Morgan."),
            fact("governing_state", "FL",
                 "This will is governed by Florida law."),
            fact("poa_agent", "Pat Morgan",
                 "I appoint Pat Morgan as my POA agent."),
        ], "will"),
        document("MORGAN-TRUST-2021", [
            fact("trust_owned_account", "Morgan Family Trust", TRUST_QUOTE,
                 "DEMO-MORGAN-BROKERAGE"),
        ], "trust"),
    ]
    original = deepcopy(docs)

    first = reconcile(docs, client, client["accounts"])
    second = reconcile(docs, client, client["accounts"])

    assert sorted(priorities(first)) == ["critical", "high", "high", "review"]
    assert [f["findingId"] for f in first["findings"]] == [
        f["findingId"] for f in second["findings"]
    ]
    assert len({f["findingId"] for f in first["findings"]}) == 4
    assert docs == original


def test_clean_client_raises_no_false_alarms_with_new_facts():
    patel = load_client("patel")
    docs = [document("PATEL-WILL", [
        fact("residuary_beneficiary", "Alex Patel",
             "The residue goes to Alex Patel and Jamie Patel."),
        fact("residuary_beneficiary", "Jamie Patel",
             "The residue goes to Alex Patel and Jamie Patel."),
        fact("governing_state", "GA", "Governed by Georgia law."),
        fact("executor", "Lee Patel", "Lee Patel is executor."),
    ], "will")]

    result = reconcile(docs, patel, patel["accounts"])

    assert result["findings"] == []


def test_validation_warning_dicts_become_plain_strings():
    client = load_client("morgan")
    docs = state_doc("GA")
    docs[0]["warnings"] = [{
        "code": "unsupported_fact",
        "message": "Excluded executor 'X': quote not found",
        "fact": {"field": "executor"},
    }]

    result = reconcile(docs, client, client["accounts"])

    assert result["warnings"] == ["Excluded executor 'X': quote not found"]
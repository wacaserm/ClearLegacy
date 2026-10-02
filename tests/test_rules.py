"""Tests for the beneficiary comparison rules."""

import json
from copy import deepcopy
from pathlib import Path

from core.rules import reconcile


ROOT = Path(__file__).resolve().parents[1]


def load_client(client_id):
    with open(ROOT / "data" / "clients.json", encoding="utf-8") as file:
        clients = json.load(file)["clients"]

    return next(
        client for client in clients
        if client["clientId"] == client_id
    )


def fact(
    name,
    account,
    tier,
    allocation,
    quote,
    field="intended_beneficiary",
):
    return {
        "field": field,
        "value": name,
        "location": "page 1",
        "quote": quote,
        "accountRef": account,
        "tier": tier,
        "allocation": allocation,
        "relationship": None,
        "asOf": None,
    }


def document(source_id, facts):
    return {
        "sourceId": source_id,
        "docType": "planning_summary",
        "facts": facts,
        "warnings": [],
    }


def morgan_facts():
    primary_quote = (
        "I want Casey Morgan to receive 100% as primary "
        "beneficiary of my IRA DEMO-MORGAN-IRA."
    )
    contingent_quote = (
        "If Casey cannot inherit, I want Avery Morgan and "
        "Riley Morgan to be contingent beneficiaries of that "
        "IRA, equally at 50% each."
    )
    brokerage_quote = (
        "For brokerage account DEMO-MORGAN-BROKERAGE, "
        "I want Avery Morgan and Riley Morgan as primary "
        "transfer-on-death beneficiaries, equally at 50% each."
    )

    return [
        document(
            "MORGAN-PLAN-2026-09-25",
            [
                fact(
                    "Casey Morgan",
                    "DEMO-MORGAN-IRA",
                    "primary",
                    "100%",
                    primary_quote,
                ),
                fact(
                    "Avery Morgan",
                    "DEMO-MORGAN-IRA",
                    "contingent",
                    "50%",
                    contingent_quote,
                ),
                fact(
                    "Riley Morgan",
                    "DEMO-MORGAN-IRA",
                    "contingent",
                    "50%",
                    contingent_quote,
                ),
                fact(
                    "Avery Morgan",
                    "DEMO-MORGAN-BROKERAGE",
                    "primary",
                    "50%",
                    brokerage_quote,
                ),
                fact(
                    "Riley Morgan",
                    "DEMO-MORGAN-BROKERAGE",
                    "primary",
                    "50%",
                    brokerage_quote,
                ),
            ],
        )
    ]


def patel_facts():
    ira_quote = (
        "For IRA DEMO-PATEL-IRA, Lee Patel should be primary "
        "beneficiary at 100%, with Alex Patel and Jamie Patel "
        "contingent at 50% each."
    )
    brokerage_quote = (
        "For brokerage account DEMO-PATEL-BROKERAGE, "
        "Alex Patel and Jamie Patel should be primary "
        "transfer-on-death beneficiaries at 50% each."
    )

    return [
        document(
            "PATEL-PLAN-2026-09-20",
            [
                fact(
                    "Lee Patel",
                    "DEMO-PATEL-IRA",
                    "primary",
                    "100%",
                    ira_quote,
                ),
                fact(
                    "Alex Patel",
                    "DEMO-PATEL-IRA",
                    "contingent",
                    "50%",
                    ira_quote,
                ),
                fact(
                    "Jamie Patel",
                    "DEMO-PATEL-IRA",
                    "contingent",
                    "50%",
                    ira_quote,
                ),
                fact(
                    "Alex Patel",
                    "DEMO-PATEL-BROKERAGE",
                    "primary",
                    "50%",
                    brokerage_quote,
                ),
                fact(
                    "Jamie Patel",
                    "DEMO-PATEL-BROKERAGE",
                    "primary",
                    "50%",
                    brokerage_quote,
                ),
            ],
        )
    ]


def test_morgan_has_two_ira_findings():
    client = load_client("morgan")

    result = reconcile(
        morgan_facts(),
        client,
        client["accounts"],
    )

    assert result["status"] == "review_needed"
    assert len(result["findings"]) == 2
    assert result["clarificationQuestions"] == []

    account_fields = {
        evidence["field"]
        for finding in result["findings"]
        for evidence in finding["evidence"]
        if evidence["sourceType"] == "account"
    }

    assert "primaryBeneficiaries" in account_fields
    assert "contingentBeneficiaries" in account_fields

    for finding in result["findings"]:
        account_evidence = [
            evidence
            for evidence in finding["evidence"]
            if evidence["sourceType"] == "account"
        ]

        assert all(
            evidence["sourceId"] == "DEMO-MORGAN-IRA"
            for evidence in account_evidence
        )

    assert {
        finding["priority"]
        for finding in result["findings"]
    } == {"high", "review"}


def test_patel_has_no_discrepancies():
    client = load_client("patel")

    result = reconcile(
        patel_facts(),
        client,
        client["accounts"],
    )

    assert result["status"] == "no_discrepancies_found"
    assert result["findings"] == []
    assert result["clarificationQuestions"] == []
    assert result["warnings"] == []
    assert len(result["scope"]["compared"]) == 3


def test_rivera_needs_information():
    client = load_client("rivera")

    quote = (
        "I want to make sure Harper is provided for. "
        "I have not decided whether that should be through "
        "my IRA, my brokerage account, insurance, or other arrangements."
    )

    facts = [
        document(
            "RIVERA-DISCUSSION-2026-09-24",
            [
                fact(
                    "Account-specific intentions for Harper are undecided.",
                    None,
                    None,
                    None,
                    quote,
                    field="unspecified_intention",
                )
            ],
        )
    ]

    result = reconcile(facts, client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []

    questions = " ".join(result["clarificationQuestions"])

    assert "Harper" in questions
    assert "DEMO-RIVERA-IRA" in questions
    assert "DEMO-RIVERA-BROKERAGE" in questions


def test_no_facts_is_not_a_clean_result():
    client = load_client("patel")

    result = reconcile([], client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert result["clarificationQuestions"]


def test_unknown_contingents_are_not_reported_as_missing():
    client = load_client("morgan")
    accounts = deepcopy(client["accounts"])

    ira = next(
        account for account in accounts
        if account["accountId"] == "DEMO-MORGAN-IRA"
    )
    ira["contingentBeneficiaries"] = None
    ira["contingentDataStatus"] = "not_supplied"

    result = reconcile(morgan_facts(), client, accounts)

    # The primary mismatch remains, but unknown contingents
    # should produce a question rather than a second finding.
    assert len(result["findings"]) == 1
    assert result["findings"][0]["priority"] == "high"

    assert any(
        "contingent" in question
        for question in result["clarificationQuestions"]
    )


def test_percentage_difference_is_detected():
    client = load_client("patel")
    accounts = deepcopy(client["accounts"])

    brokerage = next(
        account for account in accounts
        if account["accountId"] == "DEMO-PATEL-BROKERAGE"
    )

    brokerage["primaryBeneficiaries"][0]["percentage"] = 60
    brokerage["primaryBeneficiaries"][1]["percentage"] = 40

    result = reconcile(patel_facts(), client, accounts)

    assert result["status"] == "review_needed"
    assert len(result["findings"]) == 1

    assert any(
        evidence["sourceId"] == "DEMO-PATEL-BROKERAGE"
        for evidence in result["findings"][0]["evidence"]
        if evidence["sourceType"] == "account"
    )


def test_partial_extraction_requests_clarification():
    client = load_client("patel")
    facts = patel_facts()

    # Simulate extraction missing Jamie's contingent allocation.
    facts[0]["facts"] = [
        item
        for item in facts[0]["facts"]
        if not (
            item["value"] == "Jamie Patel"
            and item["tier"] == "contingent"
        )
    ]

    result = reconcile(facts, client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert any(
        "complete contingent allocation" in question
        for question in result["clarificationQuestions"]
    )


def test_validation_warning_prevents_clean_status():
    client = load_client("patel")
    facts = patel_facts()

    facts[0]["warnings"] = [
        {
            "code": "unsupported_fact",
            "message": "A fact was excluded during validation.",
        }
    ]

    result = reconcile(facts, client, client["accounts"])

    assert result["status"] == "needs_information"
    assert result["findings"] == []
    assert result["warnings"]


def test_findings_preserve_document_and_account_evidence():
    client = load_client("morgan")
    facts = morgan_facts()

    result = reconcile(facts, client, client["accounts"])

    valid_quotes = {
        item["quote"]
        for item in facts[0]["facts"]
    }

    for finding in result["findings"]:
        evidence_types = {
            evidence["sourceType"]
            for evidence in finding["evidence"]
        }

        assert evidence_types == {"document", "account"}

        for evidence in finding["evidence"]:
            if evidence["sourceType"] == "document":
                assert evidence["quote"] in valid_quotes
                assert evidence["location"] == "page 1"
                assert evidence["sourceId"] == facts[0]["sourceId"]

            elif evidence["sourceType"] == "account":
                account = next(
                    account
                    for account in client["accounts"]
                    if account["accountId"] == evidence["sourceId"]
                )

                field = evidence["field"]

                if field.endswith("Beneficiaries"):
                    assert json.loads(evidence["value"]) == account[field]
                else:
                    assert evidence["value"] == account[field]


def test_repeated_run_has_same_ids_and_does_not_change_inputs():
    client = load_client("morgan")
    facts = morgan_facts()

    original_client = deepcopy(client)
    original_facts = deepcopy(facts)

    first = reconcile(facts, client, client["accounts"])
    second = reconcile(facts, client, client["accounts"])

    assert [
        finding["findingId"]
        for finding in first["findings"]
    ] == [
        finding["findingId"]
        for finding in second["findings"]
    ]

    assert client == original_client
    assert facts == original_facts
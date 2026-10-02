"""Compare validated planning intentions with supplied account records.

Inputs:
    facts_list: List of validated document extraction dictionaries.
    client: One client dictionary from clients.json.
    accounts: That client's account dictionaries.

Output:
    Dictionary with status, findings, clarificationQuestions,
    warnings, and comparison scope.

The integration pipeline adds analysisId.
No AWS calls are made here.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json


TIER_FIELDS = {
    "primary": "primaryBeneficiaries",
    "contingent": "contingentBeneficiaries",
}


def _normalize_name(value):
    """Ignore capitalization and repeated spaces."""
    return " ".join(str(value).split()).casefold()


def _percentage(value):
    """Convert '50%' or 50 to a number; unclear values stay unknown."""
    if value is None or isinstance(value, bool):
        return None

    try:
        result = Decimal(
            str(value).strip().removesuffix("%").strip()
        )
    except InvalidOperation:
        return None

    if not result.is_finite():
        return None

    if not Decimal("0") <= result <= Decimal("100"):
        return None

    return result


def _allocation_map(rows, name_key, percentage_key):
    """Build a name-to-percentage mapping.

    Require explicit percentages totaling 100%.
    Identical repeated facts are counted only once.
    Return None when information is incomplete or inconsistent.
    """
    if not isinstance(rows, list):
        return None

    allocation = {}

    for row in rows:
        if not isinstance(row, dict):
            return None

        name = row.get(name_key)
        percentage = _percentage(row.get(percentage_key))

        if not isinstance(name, str) or not name.strip():
            return None

        if percentage is None:
            return None

        name = _normalize_name(name)

        if name in allocation and allocation[name] != percentage:
            return None

        allocation[name] = percentage

    if not allocation:
        return None

    if sum(allocation.values()) != Decimal("100"):
        return None

    return allocation


def _document_evidence(source_id, fact):
    """Preserve the supporting quote and its source location."""
    return {
        "sourceType": "document",
        "sourceId": source_id,
        "location": fact["location"],
        "quote": fact["quote"],
    }


def _finding_id(client_id, account_id, tier, evidence):
    """Generate a repeatable ID for the same comparison evidence."""
    payload = json.dumps(
        [client_id, account_id, tier, evidence],
        sort_keys=True,
        ensure_ascii=True,
    )

    digest = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:16]

    return f"beneficiary-{digest}"


def reconcile(facts_list, client, accounts):
    """Compare validated intentions with supplied account records."""
    findings = []
    questions = []
    warnings = []
    compared = []

    def ask(message):
        if message not in questions:
            questions.append(message)

    accounts_by_id = {
        account["accountId"]: account
        for account in accounts
    }

    # Group by account and tier, then by source document.
    # Never mix allocations from different documents.
    groups = defaultdict(lambda: defaultdict(list))

    if not facts_list:
        ask(
            "Supply readable planning documents "
            "and validated extracted facts."
        )

    for document in facts_list:
        source_id = document.get("sourceId")
        document_warnings = document.get("warnings") or []
        warnings.extend(document_warnings)

        if document_warnings:
            ask(
                "Review extraction or validation warnings before "
                "treating this comparison as complete."
            )

        facts = document.get("facts") or []

        if not facts:
            ask(
                f"No usable facts were supplied for "
                f"{source_id or 'a document'}. "
                "Confirm extraction succeeded."
            )

        for fact in facts:
            field = fact.get("field")

            if field in {
                "missing_information",
                "unspecified_intention",
            }:
                detail = (
                    fact.get("value")
                    or "Information is incomplete."
                )
                ask(
                    f"Clarify information from {source_id}: "
                    f"{detail}"
                )
                continue

            if field != "intended_beneficiary":
                continue

            account_id = fact.get("accountRef")
            tier = fact.get("tier")

            if not account_id or tier not in TIER_FIELDS:
                ask(
                    "Confirm the account and primary/contingent "
                    "tier for the intention naming "
                    f"{fact.get('value', 'a beneficiary')}."
                )
                continue

            if account_id not in accounts_by_id:
                ask(
                    f"Supply account records for {account_id}."
                )
                continue

            if (
                not source_id
                or not fact.get("quote")
                or not fact.get("location")
            ):
                ask(
                    f"Supply source evidence for the "
                    f"{account_id} {tier} beneficiary intention."
                )
                continue

            groups[(account_id, tier)][source_id].append(fact)

    # Surface missing account information and explicit record limits.
    for account in accounts:
        account_id = account["accountId"]

        if account.get("primaryBeneficiaries") is None:
            ask(
                f"Supply current primary beneficiary records "
                f"for {account_id}; missing data does not establish "
                "that no designation exists."
            )

        if account.get("recordNotes"):
            ask(
                f"Confirm current records for {account_id}. "
                f"Supplied record note: {account['recordNotes']}"
            )

    for (account_id, tier), sources in sorted(groups.items()):
        account = accounts_by_id[account_id]
        account_field = TIER_FIELDS[tier]

        # Conservative prototype behavior:
        # records with notes require clarification before comparison.
        if account.get("recordNotes"):
            continue

        intended_versions = []
        evidence = []
        incomplete = False

        for source_id, source_facts in sorted(sources.items()):
            allocation = _allocation_map(
                source_facts,
                "value",
                "allocation",
            )

            if allocation is None:
                incomplete = True
                ask(
                    f"Confirm the complete {tier} allocation "
                    f"for {account_id} in {source_id}, with "
                    "explicit percentages totaling 100%."
                )
                continue

            intended_versions.append(allocation)

            for fact in source_facts:
                item = _document_evidence(source_id, fact)

                if item not in evidence:
                    evidence.append(item)

        if incomplete or not intended_versions:
            continue

        intended = intended_versions[0]

        if any(
            version != intended
            for version in intended_versions[1:]
        ):
            ask(
                f"Planning sources give different {tier} "
                f"intentions for {account_id}. "
                "Confirm which instructions are current."
            )
            continue

        recorded_rows = account.get(account_field)

        if recorded_rows is None:
            ask(
                f"Supply the {tier} beneficiary record "
                f"for {account_id}; it was not included "
                "in the supplied information."
            )
            continue

        explicitly_none_listed = (
            tier == "contingent"
            and recorded_rows == []
            and account.get("contingentDataStatus")
            == "none_listed_in_snapshot"
        )

        if explicitly_none_listed:
            recorded = {}
        else:
            recorded = _allocation_map(
                recorded_rows,
                "name",
                "percentage",
            )

            if recorded is None:
                ask(
                    f"Confirm complete recorded {tier} "
                    f"beneficiaries and percentages "
                    f"for {account_id}."
                )
                continue

        compared.append({
            "accountId": account_id,
            "tier": tier,
        })

        if intended == recorded:
            continue

        evidence.append({
            "sourceType": "account",
            "sourceId": account_id,
            "field": account_field,
            "value": json.dumps(
                recorded_rows,
                sort_keys=True,
            ),
        })

        if explicitly_none_listed:
            evidence.append({
                "sourceType": "account",
                "sourceId": account_id,
                "field": "contingentDataStatus",
                "value": account["contingentDataStatus"],
            })

            title = (
                "Intended contingent beneficiaries are not "
                "listed in the supplied snapshot for "
                f"{account_id}"
            )

            explanation = (
                "The planning document names contingent "
                "beneficiaries, but the supplied snapshot "
                "lists none. Confirm the current designation "
                "before taking action."
            )

            priority = "review"

        else:
            title = (
                f"Potential {tier} beneficiary mismatch "
                f"for {account_id}"
            )

            explanation = (
                "The documented intention and supplied account "
                "record differ in beneficiary names or "
                "percentages. Confirm whether the difference "
                "is intentional."
            )

            priority = "high"

        findings.append({
            "findingId": _finding_id(
                client["clientId"],
                account_id,
                tier,
                evidence,
            ),
            "priority": priority,
            "title": title,
            "explanation": explanation,
            "evidence": evidence,
            "recommendedAction": (
                "Confirm current records and intentions "
                "with the client and review with their "
                "attorney or appropriate professional."
            ),
            "decision": None,
        })

    if not compared:
        ask(
            "Provide complete account-specific beneficiary "
            "intentions and usable account records "
            "to perform a comparison."
        )

    if findings:
        status = "review_needed"
    elif questions or warnings:
        status = "needs_information"
    else:
        status = "no_discrepancies_found"

    return {
        "status": status,
        "findings": findings,
        "clarificationQuestions": questions,
        "warnings": warnings,
        "scope": {
            "rule": "account_specific_beneficiary_comparison",
            "compared": compared,
        },
    }
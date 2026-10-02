"""Compare validated document facts with supplied account and client records.

Inputs:
    facts_list: List of validated document extraction dictionaries.
    client: One client dictionary from clients.json.
    accounts: That client's account dictionaries.

Output:
    Dictionary with status, findings, clarificationQuestions,
    warnings, and comparison scope.

Rules (plain Python, no AI):
    1. will_vs_tod: a will or trust names beneficiaries X; a TOD
       account names Y; anyone in Y who is not in X -> Critical.
       beneficiary_comparison separately compares account-specific
       intentions with account designations -> High / Review.
    2. trust_funding: document says the trust owns an account; the
       account registration does not show the trust (name taken from
       client["trustName"]) -> High.
    3. deceased_fiduciary: a fiduciary named in a document (executor,
       trustee, POA agent, ...) is marked deceased in the client
       profile (client["fiduciaries"]) -> High.
    4. governing_state: document's governing state differs from the
       client's current state (two-letter codes) -> Review.

Principle for every rule: unknown or missing data produces a
clarification question, never a finding.

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

LEGAL_DOC_TYPES = {"will", "trust"}

# Extraction field names (core/extract.py FACT_FIELDS) that name a
# fiduciary. The field name is the role.
FIDUCIARY_FIELDS = {
    "executor",
    "alternate_executor",
    "trustee",
    "successor_trustee",
    "poa_agent",
    "successor_poa_agent",
    "guardian",
}

RULES = [
    "will_vs_tod",
    "beneficiary_comparison",
    "trust_funding",
    "deceased_fiduciary",
    "governing_state",
]

ACTION = (
    "Confirm current records and intentions "
    "with the client and review with their "
    "attorney or appropriate professional."
)


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


def _has_evidence(source_id, fact):
    return bool(source_id and fact.get("quote") and fact.get("location"))


def _finding_id(client_id, key, tier, evidence, rule="beneficiary"):
    """Generate a repeatable ID for the same comparison evidence."""
    payload = json.dumps(
        [client_id, key, tier, evidence],
        sort_keys=True,
        ensure_ascii=True,
    )

    digest = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:16]

    return f"{rule}-{digest}"


def _warning_text(warning):
    """Warnings are shown as plain strings in the UI."""
    if isinstance(warning, dict):
        return warning.get("message") or json.dumps(
            warning, sort_keys=True
        )
    return str(warning)


def _add_finding(findings, finding):
    """Append a finding unless an identical one is already present."""
    if all(
        existing["findingId"] != finding["findingId"]
        for existing in findings
    ):
        findings.append(finding)


# ---------------------------------------------------------------------
# Rule 1: beneficiary comparison
# ---------------------------------------------------------------------

def _rule_beneficiary(
    facts_list, client, accounts, accounts_by_id, ask, compared
):
    findings = []

    # Group by account and tier, then by source document.
    # Never mix allocations from different documents.
    groups = defaultdict(lambda: defaultdict(list))

    for document in facts_list:
        source_id = document.get("sourceId")

        for fact in document.get("facts") or []:
            if fact.get("field") != "intended_beneficiary":
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
                ask(f"Supply account records for {account_id}.")
                continue

            if not _has_evidence(source_id, fact):
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
            "rule": "beneficiary_comparison",
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
            priority = "high"
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

        _add_finding(findings, {
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
            "recommendedAction": ACTION,
            "decision": None,
        })

    return findings


# ---------------------------------------------------------------------
# Rule 1: will or trust vs TOD designations
# ---------------------------------------------------------------------

def _rule_will_vs_tod(facts_list, client, accounts, ask, compared):
    findings = []
    named = {}
    document_evidence = []

    for document in facts_list:
        if document.get("docType") not in LEGAL_DOC_TYPES:
            continue

        source_id = document.get("sourceId")

        for fact in document.get("facts") or []:
            if fact.get("field") not in {
                "residuary_beneficiary",
                "intended_beneficiary",
            }:
                continue

            name = fact.get("value")

            if not isinstance(name, str) or not name.strip():
                continue

            if not _has_evidence(source_id, fact):
                ask(
                    f"Supply source evidence for {name}, named in "
                    f"{source_id or 'a document'}."
                )
                continue

            named[_normalize_name(name)] = name
            item = _document_evidence(source_id, fact)

            if item not in document_evidence:
                document_evidence.append(item)

    if not named:
        return findings

    for account in accounts:
        if account.get("designationType") != "TOD":
            continue

        account_id = account["accountId"]

        for tier, field in TIER_FIELDS.items():
            rows = account.get(field)

            if not isinstance(rows, list) or not rows:
                continue

            names = [
                row.get("name") for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("name"), str)
                and row["name"].strip()
            ]

            if len(names) != len(rows):
                ask(
                    f"Confirm complete recorded {tier} "
                    f"beneficiaries for {account_id}."
                )
                continue

            compared.append({
                "rule": "will_vs_tod",
                "accountId": account_id,
                "tier": tier,
            })

            not_named = [
                name for name in names
                if _normalize_name(name) not in named
            ]

            if not not_named:
                continue

            evidence = list(document_evidence) + [{
                "sourceType": "account",
                "sourceId": account_id,
                "field": field,
                "value": json.dumps(rows, sort_keys=True),
            }]

            _add_finding(findings, {
                "findingId": _finding_id(
                    client["clientId"],
                    account_id,
                    tier,
                    evidence,
                    rule="will-vs-tod",
                ),
                "priority": "critical",
                "title": (
                    f"{account_id} TOD names a {tier} beneficiary "
                    "who is not in the will or trust"
                ),
                "explanation": (
                    f"{', '.join(not_named)} is listed as a {tier} "
                    f"transfer-on-death beneficiary on {account_id} "
                    "but is not named in the will or trust. The "
                    "account designation, not the document, may "
                    "decide who receives this account. Confirm "
                    "whether this is intentional."
                ),
                "evidence": evidence,
                "recommendedAction": ACTION,
                "decision": None,
            })

    return findings


# ---------------------------------------------------------------------
# Rule 2: trust funding
# ---------------------------------------------------------------------

def _rule_trust_funding(
    facts_list, client, accounts_by_id, ask, compared
):
    findings = []
    trust_name = client.get("trustName")

    for document in facts_list:
        source_id = document.get("sourceId")

        for fact in document.get("facts") or []:
            if fact.get("field") != "trust_owned_account":
                continue

            account_id = fact.get("accountRef")

            if not account_id:
                ask(
                    "Confirm which account the trust document "
                    "says the trust owns."
                )
                continue

            if account_id not in accounts_by_id:
                ask(f"Supply account records for {account_id}.")
                continue

            if not _has_evidence(source_id, fact):
                ask(
                    "Supply source evidence for the trust ownership "
                    f"statement about {account_id}."
                )
                continue

            if not isinstance(trust_name, str) or not trust_name.strip():
                ask(
                    "Supply the trust's name in the client profile "
                    f"to check how {account_id} is registered."
                )
                continue

            account = accounts_by_id[account_id]
            registration = account.get("registration")

            if (
                not isinstance(registration, str)
                or not registration.strip()
            ):
                ask(
                    f"Supply the current registration for "
                    f"{account_id}; missing data does not establish "
                    "that the account is outside the trust."
                )
                continue

            compared.append({
                "rule": "trust_funding",
                "accountId": account_id,
            })

            if (
                _normalize_name(trust_name)
                in _normalize_name(registration)
            ):
                continue

            evidence = [
                _document_evidence(source_id, fact),
                {
                    "sourceType": "account",
                    "sourceId": account_id,
                    "field": "registration",
                    "value": registration,
                },
            ]

            _add_finding(findings, {
                "findingId": _finding_id(
                    client["clientId"],
                    account_id,
                    "registration",
                    evidence,
                    rule="trust-funding",
                ),
                "priority": "high",
                "title": (
                    f"{account_id} may not be funded into "
                    f"{trust_name}"
                ),
                "explanation": (
                    f"The document says {account_id} should be held "
                    f"by {trust_name}, but the account is registered "
                    f"as \"{registration}\". The trust may be "
                    "unfunded for this account."
                ),
                "evidence": evidence,
                "recommendedAction": ACTION,
                "decision": None,
            })

    return findings


# ---------------------------------------------------------------------
# Rule 3: deceased fiduciary
# ---------------------------------------------------------------------

def _find_fiduciary(profile, name, role):
    matches = [
        entry for entry in profile
        if isinstance(entry, dict)
        and _normalize_name(entry.get("name", "")) == _normalize_name(name)
    ]

    for entry in matches:
        if entry.get("role") == role:
            return entry

    return matches[0] if matches else None


def _rule_deceased_fiduciary(
    facts_list, client, ask, compared
):
    findings = []
    profile = client.get("fiduciaries")

    for document in facts_list:
        source_id = document.get("sourceId")

        for fact in document.get("facts") or []:
            role = fact.get("field")

            if role not in FIDUCIARY_FIELDS:
                continue

            name = fact.get("value")
            role_label = role.replace("_", " ")

            if not name or not _has_evidence(source_id, fact):
                ask(
                    "Confirm the name and source evidence for the "
                    f"{role_label} named in {source_id or 'a document'}."
                )
                continue

            if not isinstance(profile, list):
                ask(
                    "Supply the client's fiduciary records; whether "
                    f"{name} ({role_label}) is living is unknown."
                )
                continue

            entry = _find_fiduciary(profile, name, role)

            if entry is None or entry.get("status") not in {
                "living", "deceased"
            }:
                ask(
                    f"Confirm whether {name} ({role_label}) is "
                    "living; no status is on record."
                )
                continue

            compared.append({
                "rule": "deceased_fiduciary",
                "fiduciary": name,
                "role": role,
            })

            if entry["status"] != "deceased":
                continue

            evidence = [
                _document_evidence(source_id, fact),
                {
                    "sourceType": "account",
                    "sourceId": client["clientId"],
                    "filename": "Client profile",
                    "location": "fiduciaries",
                    "field": "fiduciaries",
                    "value": f"{entry['name']}, deceased",
                },
            ]

            died = entry.get("deceasedDate")
            when = f" (date recorded: {died})" if died else ""

            _add_finding(findings, {
                "findingId": _finding_id(
                    client["clientId"],
                    _normalize_name(name),
                    role,
                    evidence,
                    rule="deceased-fiduciary",
                ),
                "priority": "high",
                "title": (
                    f"{name} is named as {role_label} but is "
                    "marked deceased"
                ),
                "explanation": (
                    f"The document names {name} as {role_label}, "
                    f"but the client profile marks {name} as "
                    f"deceased{when}. A successor may need to be "
                    "named."
                ),
                "evidence": evidence,
                "recommendedAction": ACTION,
                "decision": None,
            })

    return findings


# ---------------------------------------------------------------------
# Rule 4: governing state
# ---------------------------------------------------------------------

def _rule_governing_state(
    facts_list, client, ask, compared
):
    findings = []
    client_state = client.get("state")

    for document in facts_list:
        source_id = document.get("sourceId")

        for fact in document.get("facts") or []:
            if fact.get("field") != "governing_state":
                continue

            state = fact.get("value")

            if not state or not _has_evidence(source_id, fact):
                ask(
                    "Confirm the governing state and source evidence "
                    f"for {source_id or 'a document'}."
                )
                continue

            if (
                not isinstance(client_state, str)
                or not client_state.strip()
            ):
                ask(
                    "Supply the client's current state of residence "
                    "to compare with the document's governing state."
                )
                continue

            compared.append({
                "rule": "governing_state",
                "sourceId": source_id,
            })

            if _normalize_name(state) == _normalize_name(client_state):
                continue

            evidence = [
                _document_evidence(source_id, fact),
                {
                    "sourceType": "account",
                    "sourceId": client["clientId"],
                    "filename": "Client profile",
                    "location": "profile",
                    "field": "state",
                    "value": client_state,
                },
            ]

            _add_finding(findings, {
                "findingId": _finding_id(
                    client["clientId"],
                    source_id,
                    "state",
                    evidence,
                    rule="governing-state",
                ),
                "priority": "review",
                "title": (
                    f"Document governed by {state}; client "
                    f"currently lives in {client_state}"
                ),
                "explanation": (
                    f"{source_id} names {state} law, but the "
                    f"client's current state is {client_state}. "
                    "State rules for wills, trusts and powers of "
                    "attorney can differ."
                ),
                "evidence": evidence,
                "recommendedAction": ACTION,
                "decision": None,
            })

    return findings


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

def reconcile(facts_list, client, accounts):
    """Compare validated document facts with supplied records."""
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

    if not facts_list:
        ask(
            "Supply readable planning documents "
            "and validated extracted facts."
        )

    for document in facts_list:
        source_id = document.get("sourceId")
        document_warnings = document.get("warnings") or []

        for warning in document_warnings:
            text = _warning_text(warning)

            if text not in warnings:
                warnings.append(text)

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
            if fact.get("field") in {
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

    findings += _rule_will_vs_tod(
        facts_list, client, accounts, ask, compared
    )
    findings += _rule_beneficiary(
        facts_list, client, accounts, accounts_by_id, ask, compared
    )
    findings += _rule_trust_funding(
        facts_list, client, accounts_by_id, ask, compared
    )
    findings += _rule_deceased_fiduciary(
        facts_list, client, ask, compared
    )
    findings += _rule_governing_state(
        facts_list, client, ask, compared
    )

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
            "rules": RULES,
            "compared": compared,
        },
    }
"""Wrong-client safety check: do the uploaded documents belong to the selected household?

Runs after extraction and before the rules. No AI calls. A document is only treated as a
mismatch when it clearly names a different principal client (a full first and last name
that matches neither the household client nor their spouse), or when it refers to an
account that is on file for a different household. Anything less certain is a warning.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "esq", "md", "phd", "cpa"}
_TITLES = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof"}
_JOINT = re.compile(r"\s+(?:and|&)\s+|\s*[,;/]\s*", re.IGNORECASE)


def name_parts(name: Any) -> list[str]:
	"""Lowercase name tokens without punctuation, titles, suffixes, or middle initials."""
	text = re.sub(r"[^\w\s'-]", " ", str(name or "")).replace("'", "")
	tokens = [t for t in text.lower().replace("-", " ").split() if t]
	tokens = [t for t in tokens if t not in _TITLES]
	while tokens and tokens[-1] in _SUFFIXES:
		tokens.pop()
	if len(tokens) > 2:
		tokens = [tokens[0]] + [t for t in tokens[1:-1] if len(t) > 1] + [tokens[-1]]
	return tokens


def _first_last(name: Any) -> tuple[str, str] | None:
	parts = name_parts(name)
	return (parts[0], parts[-1]) if len(parts) >= 2 else None


def _split_joint(value: Any) -> list[str]:
	"""'Jordan and Casey Morgan' -> ['Jordan Morgan', 'Casey Morgan']; 'A Morgan & B Lee' -> both."""
	pieces = [p.strip() for p in _JOINT.split(str(value or "")) if p.strip()]
	if len(pieces) > 1:
		last = name_parts(pieces[-1])
		surname = last[-1] if len(last) >= 2 else None
		pieces = [p if len(name_parts(p)) >= 2 or not surname else f"{p} {surname}" for p in pieces]
	return pieces or [str(value or "")]


def household_people(client: dict) -> list[str]:
	"""Principal names that may appear as the client on a document: client, spouse, co-client."""
	keys = ("name", "clientName", "currentSpouse", "spouse", "coClient", "coClientName")
	return [str(client[k]) for k in keys if client.get(k)]


def classify_name(value: Any, client: dict) -> str:
	"""'match', 'mismatch', or 'unclear' for one extracted client_name value."""
	people = [fl for fl in (_first_last(p) for p in household_people(client)) if fl]
	trust = name_parts(client.get("trustName"))
	verdicts = []
	for piece in _split_joint(value):
		parts = name_parts(piece)
		if not parts:
			continue
		if trust and parts == trust:
			return "match"
		if "trust" in parts:
			verdicts.append("unclear")  # a trust named as the client; let the advisor judge
			continue
		fl = (parts[0], parts[-1]) if len(parts) >= 2 else None
		if fl and fl in people:
			return "match"
		if fl and any(fl[1] == last for _, last in people):
			verdicts.append("unclear")  # same family name, different first name (nickname, relative)
		elif fl:
			verdicts.append("mismatch")
		else:
			verdicts.append("unclear")  # single word: not enough to decide
	if verdicts and all(v == "mismatch" for v in verdicts):
		return "mismatch"
	return "unclear" if verdicts else "missing"


def _account_ids(accounts: Iterable[dict] | None) -> set[str]:
	return {str(a.get("accountId")).upper() for a in accounts or [] if isinstance(a, dict) and a.get("accountId")}


def check_identity(documents: list[tuple[str, dict]], client: dict, accounts: list[dict] | None,
				   other_accounts: Iterable[str] = ()) -> dict[str, Any]:
	"""Check each (filename, validated facts) pair against the selected household.

	other_accounts: account IDs on file for other households. Returns
	{"mismatches": [{"fileName", "nameFound", "expectedName"}], "warnings": [str]}.
	"""
	expected = str(client.get("name") or client.get("clientName") or "this household")
	own = _account_ids(accounts)
	foreign = {str(a).upper() for a in other_accounts} - own
	mismatches, warnings = [], []
	for filename, facts in documents:
		fact_list = [f for f in (facts or {}).get("facts", []) or [] if isinstance(f, dict)]
		names = [f.get("value") for f in fact_list if f.get("field") == "client_name" and f.get("value")]
		verdicts = [classify_name(n, client) for n in names]
		refs = sorted({str(f.get("accountRef")).upper() for f in fact_list if f.get("accountRef")} & foreign)
		if names and all(v == "mismatch" for v in verdicts):
			mismatches.append({"fileName": filename, "nameFound": str(names[0]), "expectedName": expected})
		elif refs:
			mismatches.append({"fileName": filename, "nameFound": "an account on file for another household",
							   "expectedName": expected, "accountRefs": refs})
		elif not names or "match" not in verdicts:
			warnings.append(f"Couldn't confirm the client name on {filename}; please verify.")
	return {"mismatches": mismatches, "warnings": warnings}

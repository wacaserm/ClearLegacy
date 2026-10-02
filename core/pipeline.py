"""Orchestrate document extraction, validation, reconciliation, and persistence."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from typing import Any, Callable

from . import store
from .document_reader import read_document


def _load_function(module_name: str, function_name: str) -> tuple[Callable[..., Any] | None, str | None]:
	try:
		module = importlib.import_module(f".{module_name}", __package__)
		return getattr(module, function_name), None
	except (ImportError, AttributeError) as exc:
		return None, f"Integration blocker: {module_name}.{function_name} is unavailable ({exc.__class__.__name__})."


def _document_input(item: Any) -> dict[str, Any]:
	if isinstance(item, dict):
		return item
	if isinstance(item, (tuple, list)) and len(item) == 2:
		return read_document(item[0], str(item[1]))
	if hasattr(item, "read"):
		content = item.read()
		return read_document(content, getattr(item, "name", "upload"))
	raise TypeError("documents must contain document dictionaries, (bytes, filename) pairs, or file-like uploads.")


def _validated_facts(validation: Any) -> tuple[dict[str, Any] | None, list[str]]:
	if not isinstance(validation, dict):
		return None, ["Fact validation returned an invalid result."]
	warnings = validation.get("warnings", [])
	warnings = warnings if isinstance(warnings, list) else [str(warnings)]
	if validation.get("valid") is False or validation.get("is_valid") is False:
		return None, [str(warning) for warning in warnings] or ["Fact validation failed."]
	facts = validation.get("facts", validation.get("validatedFacts", validation))
	if not isinstance(facts, dict):
		return None, [str(warning) for warning in warnings] + ["Fact validation returned no usable facts."]
	return facts, [str(warning) for warning in warnings]


def analyze(client_id: str, documents: list[Any]) -> dict[str, Any]:
	analysis_id = f"analysis-{uuid.uuid4()}"
	result: dict[str, Any] = {
		"analysisId": analysis_id,
		"status": "failed",
		"findings": [],
		"clarificationQuestions": [],
		"warnings": [],
	}

	functions: dict[str, Callable[..., Any] | None] = {}
	for module_name, function_name in (
		("extract", "extract_facts"),
		("validation", "validate_facts"),
		("rules", "reconcile"),
		("explain", "explain"),
	):
		function, blocker = _load_function(module_name, function_name)
		functions[function_name] = function
		if blocker:
			result["warnings"].append(blocker)

	try:
		parsed_documents = [_document_input(item) for item in documents]
	except Exception as exc:
		result["warnings"].append(f"Document integration failed: {exc}")
		return result

	for document in parsed_documents:
		result["warnings"].extend(str(warning) for warning in document.get("warnings", []))
		if document.get("status") not in (None, "ok"):
			result["warnings"].append(
				f"Document {document.get('filename', 'unknown')} is not ready for comparison: "
				f"{document.get('status')}."
			)

	missing = [name for name, function in functions.items() if function is None]
	if missing:
		result["warnings"].append("Analysis is incomplete because required teammate functions are missing: " + ", ".join(missing))
		return result

	try:
		client = store.get_client(client_id)
		accounts = store.get_accounts(client_id)
	except (KeyError, ValueError, store.StoreDataMissing) as exc:
		result["warnings"].append(f"Analysis is incomplete because client/account data is unavailable: {exc}")
		return result

	validated: list[dict[str, Any]] = []
	for document in parsed_documents:
		extracted = functions["extract_facts"](document)
		validation = functions["validate_facts"](extracted, document)
		facts, warnings = _validated_facts(validation)
		result["warnings"].extend(warnings)
		if facts is not None:
			validated.append(facts)

	if len(validated) != len(parsed_documents):
		result["warnings"].append("One or more documents did not produce validated facts; comparison was not completed.")
		return result

	reconciliation = functions["reconcile"](validated, client, accounts)
	raw_findings = reconciliation.get("findings", []) if isinstance(reconciliation, dict) else []
	findings = [functions["explain"](finding) for finding in raw_findings]
	result["findings"] = findings
	result["status"] = reconciliation.get("status", "review_needed") if isinstance(reconciliation, dict) else "review_needed"
	if isinstance(reconciliation, dict):
		result["clarificationQuestions"] = reconciliation.get("clarificationQuestions", [])
		result["warnings"].extend(str(warning) for warning in reconciliation.get("warnings", []))
	store.save_findings(client_id, analysis_id, findings)
	return result

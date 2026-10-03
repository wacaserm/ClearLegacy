"""Orchestrate document extraction, validation, reconciliation, and persistence."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from typing import Any, Callable

from . import config, store
from .document_reader import read_document
from .identity import check_identity


def _load_function(module_name: str, function_name: str) -> tuple[Callable[..., Any] | None, str | None]:
	try:
		module = importlib.import_module(f".{module_name}", __package__)
		return getattr(module, function_name), None
	except (ImportError, AttributeError) as exc:
		return None, f"Integration blocker: {module_name}.{function_name} is unavailable ({exc.__class__.__name__})."


def _document_input(item: Any, client_id: str | None = None) -> dict[str, Any]:
	if isinstance(item, dict):
		return item
	if isinstance(item, (tuple, list)) and len(item) == 2:
		content, filename = item[0], str(item[1])
	elif hasattr(item, "read"):
		content, filename = item.read(), getattr(item, "name", "upload")
	else:
		raise TypeError("documents must contain document dictionaries, (bytes, filename) pairs, or file-like uploads.")
	document = read_document(content, filename)
	if client_id and config.use_s3():
		_store_in_s3(document, client_id, filename, content)
	return document


def _store_in_s3(document: dict[str, Any], client_id: str, filename: str, content: bytes) -> None:
	"""Keep an encrypted S3 copy; processing continues locally if this fails."""
	from .s3_documents import S3StorageError, store_upload

	try:
		document.update(store_upload(client_id, filename, content))
	except S3StorageError as exc:
		config.aws_warning(f"S3 storage unavailable; continuing locally ({exc}).")


def _other_household_accounts(client_id: str) -> set[str]:
	"""Account IDs on file for every other household; empty if the store can't list them."""
	ids: set[str] = set()
	try:
		for other in store.get_clients():
			other_id = other.get("clientId") or other.get("id")
			if not other_id or other_id == client_id:
				continue
			ids.update(str(a.get("accountId")) for a in store.get_accounts(other_id) or [] if a.get("accountId"))
	except Exception:
		return set()
	return ids


def _quarantine_uploads(documents: list[dict[str, Any]], filenames: set[str]) -> None:
	"""Remove the S3 copy of mismatched uploads (that exact version), or tag it quarantined.

	The bucket is versioned, so deleting the version restores the household's earlier file
	under the same key instead of leaving another client's document as the current copy.
	"""
	from .bedrock_client import get_client

	for document in documents:
		key, bucket = document.get("s3Key"), document.get("s3Bucket")
		if document.get("filename") not in filenames or not key or not bucket:
			continue
		version = {"VersionId": document["s3VersionId"]} if document.get("s3VersionId") else {}
		try:
			get_client("s3").delete_object(Bucket=bucket, Key=key, **version)
			continue
		except Exception:
			pass
		try:
			get_client("s3").put_object_tagging(
				Bucket=bucket, Key=key, **version,
				Tagging={"TagSet": [{"Key": "clearlegacy-status", "Value": "quarantined-client-mismatch"}]},
			)
		except Exception as exc:
			config.aws_warning(f"Could not remove or quarantine the S3 copy of {document.get('filename')} ({exc.__class__.__name__}).")


def _validated_facts(validation: Any) -> tuple[dict[str, Any] | None, list[str]]:
	if not isinstance(validation, dict):
		return None, ["Fact validation returned an invalid result."]
	warnings = validation.get("warnings", [])
	warnings = warnings if isinstance(warnings, list) else [str(warnings)]
	if validation.get("valid") is False or validation.get("is_valid") is False:
		return None, [str(warning) for warning in warnings] or ["Fact validation failed."]
	# validate_facts returns the facts dict itself, whose "facts" key is the list of facts.
	if isinstance(validation.get("facts"), list):
		facts = validation
	else:
		facts = validation.get("facts", validation.get("validatedFacts", validation))
	if not isinstance(facts, dict):
		return None, [str(warning) for warning in warnings] + ["Fact validation returned no usable facts."]
	return facts, [str(warning) for warning in warnings]


def _report(progress: Callable[..., Any] | None, step: str, detail: str | None = None) -> None:
	"""Tell an optional progress callback which step is running; never let it break analysis."""
	if progress is None:
		return
	try:
		progress(step, detail)
	except Exception:
		pass


def analyze(client_id: str, documents: list[Any], progress: Callable[..., Any] | None = None) -> dict[str, Any]:
	"""Run the analysis. Optional progress(step, detail) is called with step names:
	reading, ocr, extracting, checking, comparing, explaining. Unused by default."""
	from .bedrock_client import usage_since, usage_snapshot

	before = usage_snapshot()
	result = _analyze(client_id, documents, progress)
	result["usage"] = usage_since(before)  # Bedrock tokens and estimated cost for this analysis
	# Surface any AWS fallbacks (OCR, S3, DynamoDB, masking) that happened during this run.
	for warning in config.drain_warnings():
		if warning not in result["warnings"]:
			result["warnings"].append(warning)
	return result


def _analyze(client_id: str, documents: list[Any], progress: Callable[..., Any] | None = None) -> dict[str, Any]:
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

	_report(progress, "reading", f"{len(documents)} document(s)")
	try:
		parsed_documents = [_document_input(item, client_id) for item in documents]
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

	ocr_documents = [d for d in parsed_documents if d.get("ocrPages")]
	if ocr_documents:
		_report(progress, "ocr", f"{len(ocr_documents)} scanned document(s)")

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
	for index, document in enumerate(parsed_documents, start=1):
		_report(progress, "extracting", f"{document.get('filename', 'document')} ({index} of {len(parsed_documents)})")
		extracted = functions["extract_facts"](document)
		_report(progress, "checking", document.get("filename", "document"))
		validation = functions["validate_facts"](extracted, document)
		facts, warnings = _validated_facts(validation)
		result["warnings"].extend(warnings)
		if facts is not None:
			validated.append(facts)

	if len(validated) != len(parsed_documents):
		result["warnings"].append("One or more documents did not produce validated facts; comparison was not completed.")
		return result

	# Wrong-client safety check: stop before the rules if a document belongs to another household.
	identity = check_identity(
		[(document.get("filename", "document"), facts) for document, facts in zip(parsed_documents, validated)],
		client, accounts, _other_household_accounts(client_id),
	)
	result["warnings"].extend(identity["warnings"])
	if identity["mismatches"]:
		_quarantine_uploads(parsed_documents, {m["fileName"] for m in identity["mismatches"]})
		result["status"] = "client_mismatch"
		result["clientMismatch"] = identity["mismatches"]
		return result  # no rules, explanations, summary, or saved findings

	_report(progress, "comparing", f"{len(accounts)} account record(s)")
	reconciliation = functions["reconcile"](validated, client, accounts)
	raw_findings = reconciliation.get("findings", []) if isinstance(reconciliation, dict) else []
	if raw_findings:
		_report(progress, "explaining", f"{len(raw_findings)} finding(s)")
	findings = [functions["explain"](finding) for finding in raw_findings]
	result["findings"] = findings
	result["status"] = reconciliation.get("status", "review_needed") if isinstance(reconciliation, dict) else "review_needed"
	if isinstance(reconciliation, dict):
		result["clarificationQuestions"] = reconciliation.get("clarificationQuestions", [])
		result["warnings"].extend(str(warning) for warning in reconciliation.get("warnings", []))
	store.save_findings(client_id, analysis_id, findings)
	return result

"""JSON-backed fixture and runtime storage for the ClearLegacy prototype."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
	import fcntl
except ImportError:  # pragma: no cover - the workshop target is macOS/Linux.
	fcntl = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNTIME_DIR = Path(os.environ.get("CLEARLEGACY_RUNTIME_DIR", DATA_DIR / "runtime"))
CLIENTS_FILE = DATA_DIR / "clients.json"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class StoreDataMissing(FileNotFoundError):
	"""Raised when the repository has not supplied structured client data."""


def _validate_identifier(value: str, label: str) -> str:
	if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
		raise ValueError(f"Invalid {label}: identifiers may contain only letters, numbers, '.', '_' and '-'.")
	return value


def _load_json(path: Path) -> Any:
	try:
		with path.open(encoding="utf-8") as handle:
			return json.load(handle)
	except json.JSONDecodeError as exc:
		raise StoreDataMissing(f"Structured store file is invalid JSON: {path}") from exc


def _client_records() -> list[dict[str, Any]]:
	if not CLIENTS_FILE.exists():
		raise StoreDataMissing(
			f"Missing client/account records: expected client records at {CLIENTS_FILE} and account records at "
			f"{ACCOUNTS_FILE} or nested in clients.json. Existing sample_data contains documents only."
		)
	records = _load_json(CLIENTS_FILE)
	if isinstance(records, dict) and isinstance(records.get("clients"), list):
		records = records["clients"]
	if not isinstance(records, list):
		raise StoreDataMissing(f"Client records must be a JSON list: {CLIENTS_FILE}")
	return records


def get_clients() -> list[dict[str, Any]]:
	return _client_records()


def get_client(client_id: str) -> dict[str, Any]:
	client_id = _validate_identifier(client_id, "client_id")
	for client in _client_records():
		if client.get("clientId") == client_id or client.get("id") == client_id:
			return client
	raise KeyError(f"Client record not found: {client_id}")


def get_accounts(client_id: str) -> list[dict[str, Any]]:
	client_id = _validate_identifier(client_id, "client_id")
	client = _JSON_FUNCTIONS["get_client"](client_id)  # stay on JSON when used as the fallback
	nested = client.get("accounts")
	if isinstance(nested, list):
		return nested
	if ACCOUNTS_FILE.exists():
		accounts = _load_json(ACCOUNTS_FILE)
		if not isinstance(accounts, list):
			raise StoreDataMissing(f"Account records must be a JSON list: {ACCOUNTS_FILE}")
		return [account for account in accounts if account.get("clientId") == client_id]
	raise StoreDataMissing(
		f"Missing account records for client {client_id}: expected nested accounts or {ACCOUNTS_FILE}."
	)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
	path.parent.mkdir(parents=True, exist_ok=True)
	lock_path = path.with_name(f".{path.name}.lock")
	with lock_path.open("a+") as lock_file:
		if fcntl is not None:
			fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
		try:
			yield
		finally:
			if fcntl is not None:
				fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, value: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
	try:
		with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
			json.dump(value, handle, indent=2, sort_keys=True)
			handle.write("\n")
			handle.flush()
			os.fsync(handle.fileno())
		os.replace(temporary_name, path)
	finally:
		if os.path.exists(temporary_name):
			os.unlink(temporary_name)


def save_findings(client_id: str, analysis_id: str, findings: list[dict[str, Any]]) -> None:
	client_id = _validate_identifier(client_id, "client_id")
	analysis_id = _validate_identifier(analysis_id, "analysis_id")
	if not isinstance(findings, list):
		raise ValueError("findings must be a list.")
	path = RUNTIME_DIR / f"findings-{client_id}-{analysis_id}.json"
	with _locked(path):
		_atomic_write(path, {"clientId": client_id, "analysisId": analysis_id, "findings": findings})


def log_decision(
	client_id: str,
	analysis_id: str,
	finding_id: str,
	decision: str,
	user: str,
	note: str,
) -> None:
	client_id = _validate_identifier(client_id, "client_id")
	analysis_id = _validate_identifier(analysis_id, "analysis_id")
	finding_id = _validate_identifier(finding_id, "finding_id")
	if not isinstance(decision, str) or not decision.strip():
		raise ValueError("decision must be a non-empty string.")
	if not isinstance(user, str) or not user.strip():
		raise ValueError("user must be a non-empty string.")
	if not isinstance(note, str):
		raise ValueError("note must be a string.")

	path = RUNTIME_DIR / f"audit-{client_id}.json"
	with _locked(path):
		history = _load_json(path) if path.exists() else []
		if not isinstance(history, list):
			raise ValueError(f"Audit history is not a JSON list: {path}")
		history.append(
			{
				"auditId": str(uuid.uuid4()),
				"clientId": client_id,
				"analysisId": analysis_id,
				"findingId": finding_id,
				"decision": decision.strip(),
				"user": user.strip(),
				"note": note,
				"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			}
		)
		_atomic_write(path, history)


def get_audit(client_id: str) -> list[dict[str, Any]]:
	client_id = _validate_identifier(client_id, "client_id")
	path = RUNTIME_DIR / f"audit-{client_id}.json"
	if not path.exists():
		return []
	with _locked(path):
		history = _load_json(path)
	if not isinstance(history, list):
		raise ValueError(f"Audit history is not a JSON list: {path}")
	return history


# --------------------------------------------------------------------------- backend selection
# CLEARLEGACY_STORAGE=dynamodb routes these functions to core/store_dynamodb.py
# (same names and return shapes). Any DynamoDB error falls back to the JSON
# functions above with a visible warning. Default "json" is unchanged behavior.

_JSON_FUNCTIONS = {
	"get_clients": get_clients,
	"get_client": get_client,
	"get_accounts": get_accounts,
	"save_findings": save_findings,
	"log_decision": log_decision,
	"get_audit": get_audit,
}


def _check_inputs(name: str, args: tuple, kwargs: dict) -> None:
	"""Apply the JSON store's input validation before any backend runs."""
	names = {
		"get_client": ["client_id"],
		"get_accounts": ["client_id"],
		"get_audit": ["client_id"],
		"save_findings": ["client_id", "analysis_id", "findings"],
		"log_decision": ["client_id", "analysis_id", "finding_id", "decision", "user", "note"],
	}.get(name, [])
	values = dict(zip(names, args), **kwargs)
	for key in ("client_id", "analysis_id", "finding_id"):
		if key in values:
			_validate_identifier(values[key], key)
	if name == "save_findings" and not isinstance(values.get("findings"), list):
		raise ValueError("findings must be a list.")
	if name == "log_decision":
		if not isinstance(values.get("decision"), str) or not values["decision"].strip():
			raise ValueError("decision must be a non-empty string.")
		if not isinstance(values.get("user"), str) or not values["user"].strip():
			raise ValueError("user must be a non-empty string.")
		if not isinstance(values.get("note"), str):
			raise ValueError("note must be a string.")


def _select_backend(name: str):
	json_function = _JSON_FUNCTIONS[name]

	def dispatch(*args, **kwargs):
		from . import config

		if config.storage() == "dynamodb":
			_check_inputs(name, args, kwargs)
			from . import store_dynamodb

			try:
				return getattr(store_dynamodb, name)(*args, **kwargs)
			except store_dynamodb.StoreBackendError as exc:
				config.aws_warning(f"DynamoDB unavailable; using local JSON storage ({exc}).")
			except KeyError as exc:
				if name not in {"get_client", "get_accounts"}:
					raise
				config.aws_warning(f"{exc.args[0]} in DynamoDB; using local JSON records (run infra/seed_dynamodb.py).")
		return json_function(*args, **kwargs)

	dispatch.__name__ = name
	dispatch.__doc__ = json_function.__doc__
	return dispatch


for _name in _JSON_FUNCTIONS:
	globals()[_name] = _select_backend(_name)


def backend_name() -> str:
	"""Configured storage backend ('json' or 'dynamodb'), for display."""
	from . import config

	return config.storage()

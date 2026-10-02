"""DynamoDB backend with the same functions and return shapes as core/store.py.

Selected with CLEARLEGACY_STORAGE=dynamodb. Any AWS error raises
StoreBackendError so core/store.py can fall back to local JSON with a warning.

Tables (created by infra/setup_aws.py, prefix CLEARLEGACY_TABLE_PREFIX):
  clients  pk clientId                       (seeded from data/clients.json)
  accounts pk clientId, sk accountId         (seeded)
  findings pk clientId, sk findingId = "<analysisId>#<findingId>"
  audit    pk clientId, sk sk = "<timestamp>#<auditId>", append-only
"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

from core import config
from core.bedrock_client import get_client as aws_client  # store's own get_client is below


class StoreBackendError(RuntimeError):
    """DynamoDB could not be used; core/store.py falls back to JSON."""


_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _client():
    return aws_client("dynamodb")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_item(value: dict) -> dict:
    plain = json.loads(json.dumps(value), parse_float=Decimal)
    return {k: _serializer.serialize(v) for k, v in plain.items()}


def _plain(value: Any) -> Any:
    """Decimal -> int/float, recursively, so shapes match the JSON store."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _from_item(item: dict) -> dict:
    return _plain({k: _deserializer.deserialize(v) for k, v in item.items()})


def _call(operation: str, **kwargs):
    try:
        return getattr(_client(), operation)(**kwargs)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise
        raise StoreBackendError(f"DynamoDB {operation} failed: {error.response['Error']['Code']}") from error
    except BotoCoreError as error:
        raise StoreBackendError(f"DynamoDB {operation} failed: {error}") from error


def _query(table: str, client_id: str) -> list[dict]:
    items, start = [], None
    while True:
        kwargs = {
            "TableName": table,
            "KeyConditionExpression": "#pk = :pk",
            "ExpressionAttributeNames": {"#pk": "clientId"},
            "ExpressionAttributeValues": {":pk": {"S": client_id}},
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = _call("query", **kwargs)
        items.extend(_from_item(i) for i in page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _account(item: dict) -> dict:
    meta = item.pop("_meta", {}) or {}
    if meta.get("addedClientId"):
        item.pop("clientId", None)
    return item


def _accounts_for(client_id: str) -> list[dict]:
    items = sorted(_query(config.table_name("accounts"), client_id), key=lambda a: (a.get("_meta") or {}).get("order", 0))
    return [_account(item) for item in items]


def _client_record(item: dict) -> dict:
    meta = item.pop("_meta", {}) or {}
    if meta.get("hasAccounts", True):
        item["accounts"] = _accounts_for(item["clientId"])
    return item


def get_clients() -> list[dict[str, Any]]:
    items, start = [], None
    while True:
        kwargs = {"TableName": config.table_name("clients")}
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = _call("scan", **kwargs)
        items.extend(_from_item(i) for i in page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    if not items:
        raise StoreBackendError("the DynamoDB clients table is empty (run infra/seed_dynamodb.py)")
    items.sort(key=lambda c: (c.get("_meta") or {}).get("order", 0))
    return [_client_record(item) for item in items]


def get_client(client_id: str) -> dict[str, Any]:
    response = _call("get_item", TableName=config.table_name("clients"), Key={"clientId": {"S": client_id}})
    if "Item" not in response:
        raise KeyError(f"Client record not found: {client_id}")
    return _client_record(_from_item(response["Item"]))


def get_accounts(client_id: str) -> list[dict[str, Any]]:
    get_client(client_id)  # same KeyError as the JSON store for unknown clients
    return _accounts_for(client_id)


def save_findings(client_id: str, analysis_id: str, findings: list[dict[str, Any]]) -> None:
    table = config.table_name("findings")
    saved_at = _timestamp()
    # One summary row per analysis, so an analysis with zero findings is still recorded.
    _call("put_item", TableName=table, Item=_to_item({
        "clientId": client_id, "findingId": f"{analysis_id}#_analysis",
        "analysisId": analysis_id, "findingCount": len(findings), "savedAt": saved_at,
    }))
    for index, finding in enumerate(findings):
        finding_id = str(finding.get("findingId") or f"finding-{index + 1}")
        _call("put_item", TableName=table, Item=_to_item({
            "clientId": client_id, "findingId": f"{analysis_id}#{finding_id}",
            "analysisId": analysis_id, "finding": finding, "savedAt": saved_at,
        }))


def log_decision(client_id: str, analysis_id: str, finding_id: str, decision: str, user: str, note: str) -> None:
    entry = {
        "auditId": str(uuid.uuid4()),
        "clientId": client_id,
        "analysisId": analysis_id,
        "findingId": finding_id,
        "decision": decision.strip(),
        "user": user.strip(),
        "note": note,
        "timestamp": _timestamp(),
    }
    try:
        # Append-only: the write fails if an entry with this key already exists.
        _call(
            "put_item",
            TableName=config.table_name("audit"),
            Item=_to_item({**entry, "sk": f"{entry['timestamp']}#{entry['auditId']}"}),
            ConditionExpression="attribute_not_exists(clientId) AND attribute_not_exists(sk)",
        )
    except ClientError as error:
        raise StoreBackendError("audit entry already exists; the audit log is append-only") from error


def get_audit(client_id: str) -> list[dict[str, Any]]:
    entries = _query(config.table_name("audit"), client_id)
    for entry in entries:
        entry.pop("sk", None)
    return entries

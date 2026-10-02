"""Load data/clients.json into the DynamoDB clients and accounts tables. Safe to rerun.

Usage: python infra/seed_dynamodb.py
Reads table names from CLEARLEGACY_TABLE_PREFIX (default "clearlegacy-").
Client and account records are reference data for matching, so they are not
PII-masked.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402


def to_dynamo(value):
    """Floats become Decimal (DynamoDB rejects float)."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def main() -> None:
    data = json.loads((ROOT / "data" / "clients.json").read_text(encoding="utf-8"))
    clients = data["clients"] if isinstance(data, dict) else data
    dynamodb = boto3.resource("dynamodb", region_name=config.REGION)
    clients_table = dynamodb.Table(config.table_name("clients"))
    accounts_table = dynamodb.Table(config.table_name("accounts"))

    for client in clients:
        record = {k: v for k, v in client.items() if k != "accounts"}
        clients_table.put_item(Item=to_dynamo(record))
        with accounts_table.batch_writer() as batch:
            for account in client.get("accounts", []):
                batch.put_item(Item=to_dynamo({**account, "clientId": client["clientId"]}))
        print(f"seeded {client['clientId']}: {len(client.get('accounts', []))} account(s)")


if __name__ == "__main__":
    main()

"""One store contract, run against both backends: local JSON and DynamoDB (in-memory fake).

Also checks the DynamoDB -> JSON fallback and append-only audit writes.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from boto3.dynamodb.types import TypeSerializer

import core.store as store
import core.store_dynamodb as store_dynamodb
from core import config
from tests.fake_dynamodb import BrokenDynamoDB, FakeDynamoDB

CLIENTS = json.loads((Path(__file__).parent.parent / "data" / "clients.json").read_text())["clients"]
FINDING = {"findingId": "F1", "priority": "high", "title": "Mismatch", "score": 0.5,
           "evidence": [{"sourceType": "account", "sourceId": "DEMO-MORGAN-IRA", "field": "primaryBeneficiaries",
                         "value": "Taylor Morgan 100%"}]}


def _seed(fake):
    """Same item shapes as infra/seed_dynamodb.py."""
    ser = TypeSerializer()

    def item(value):
        return {k: ser.serialize(v) for k, v in json.loads(json.dumps(value), parse_float=Decimal).items()}

    for index, client in enumerate(CLIENTS):
        record = {k: v for k, v in client.items() if k != "accounts"}
        record["_meta"] = {"order": index, "hasAccounts": True}
        fake.put_item(TableName="clearlegacy-clients", Item=item(record))
        for position, account in enumerate(client["accounts"]):
            fake.put_item(TableName="clearlegacy-accounts", Item=item(
                {**account, "clientId": client["clientId"], "_meta": {"order": position, "addedClientId": True}}))


@pytest.fixture(params=["json", "dynamodb"])
def backend(request, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    config.drain_warnings()
    if request.param == "dynamodb":
        fake = FakeDynamoDB()
        _seed(fake)
        monkeypatch.setenv("CLEARLEGACY_STORAGE", "dynamodb")
        monkeypatch.setattr(store_dynamodb, "_client", lambda: fake)
        yield fake
    else:
        monkeypatch.setenv("CLEARLEGACY_STORAGE", "json")
        yield None
    assert config.drain_warnings() == []  # no silent fallback during contract tests


def test_clients_and_accounts_match_clients_json(backend):
    assert store.get_clients() == CLIENTS  # same records, order, nesting, and int types
    assert store.get_client("morgan") == CLIENTS[0]
    assert store.get_accounts("patel") == CLIENTS[1]["accounts"]
    assert isinstance(store.get_accounts("morgan")[0]["primaryBeneficiaries"][0]["percentage"], int)


def test_unknown_client_and_bad_ids_raise_like_json(backend):
    with pytest.raises(ValueError):
        store.get_client("bad id!")
    with pytest.raises(ValueError):
        store.log_decision("morgan", "a1", "F1", "  ", "advisor", "")


def test_findings_and_audit_round_trip(backend):
    store.save_findings("morgan", "analysis-1", [FINDING])
    store.log_decision("morgan", "analysis-1", "F1", "confirm", "advisor", "Checked with client")
    store.log_decision("morgan", "analysis-1", "F1", "attorney_review", "advisor", "")
    audit = store.get_audit("morgan")
    assert [a["decision"] for a in audit] == ["confirm", "attorney_review"]
    assert set(audit[0]) == {"auditId", "clientId", "analysisId", "findingId", "decision", "user", "note", "timestamp"}
    assert store.get_audit("patel") == []
    if backend is not None:
        saved = [k for k in backend.tables["clearlegacy-findings"]]
        assert ("morgan", "analysis-1#F1") in saved and ("morgan", "analysis-1#_analysis") in saved


def test_dynamodb_audit_is_append_only(monkeypatch):
    fake = FakeDynamoDB()
    monkeypatch.setattr(store_dynamodb, "_client", lambda: fake)
    monkeypatch.setattr(store_dynamodb, "_timestamp", lambda: "2026-10-02T00:00:00Z")
    monkeypatch.setattr(store_dynamodb.uuid, "uuid4", lambda: "same-id")
    store_dynamodb.log_decision("morgan", "a", "F1", "confirm", "advisor", "")
    with pytest.raises(store_dynamodb.StoreBackendError, match="append-only"):
        store_dynamodb.log_decision("morgan", "a", "F1", "dismiss", "advisor", "")  # same key: refused
    entries = store_dynamodb.get_audit("morgan")
    assert [e["decision"] for e in entries] == ["confirm"]  # original entry unchanged


def test_dynamodb_errors_fall_back_to_json_with_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv("CLEARLEGACY_STORAGE", "dynamodb")
    monkeypatch.setattr(store_dynamodb, "_client", lambda: BrokenDynamoDB())
    config.drain_warnings()
    assert store.get_clients() == CLIENTS
    store.log_decision("morgan", "a1", "F1", "confirm", "advisor", "")
    assert len(store.get_audit("morgan")) == 1
    warnings = config.drain_warnings()
    assert warnings and all("DynamoDB unavailable" in w for w in warnings)


def test_unseeded_table_falls_back(monkeypatch):
    monkeypatch.setenv("CLEARLEGACY_STORAGE", "dynamodb")
    monkeypatch.setattr(store_dynamodb, "_client", lambda: FakeDynamoDB())
    config.drain_warnings()
    assert store.get_clients() == CLIENTS
    assert any("seed_dynamodb" in w for w in config.drain_warnings())


def test_real_client_lookup_returns_a_dynamodb_client():
    # Regression: store_dynamodb.get_client must not shadow the AWS client helper.
    client = store_dynamodb._client()
    assert client.meta.service_model.service_name == "dynamodb"

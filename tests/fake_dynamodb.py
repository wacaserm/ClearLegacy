"""Minimal in-memory DynamoDB client for store tests: get/put (with
attribute_not_exists conditions), query on the partition key, and scan."""

from botocore.exceptions import ClientError

KEYS = {"clients": ("clientId", None), "accounts": ("clientId", "accountId"),
        "findings": ("clientId", "findingId"), "audit": ("clientId", "sk")}


class FakeDynamoDB:
    def __init__(self, prefix="clearlegacy-"):
        self.prefix = prefix
        self.tables = {f"{prefix}{name}": {} for name in KEYS}
        self.calls = []

    def _key(self, table, item):
        pk, sk = KEYS[table[len(self.prefix):]]
        return (item[pk]["S"], item[sk]["S"] if sk else None)

    def put_item(self, TableName, Item, ConditionExpression=None):
        self.calls.append("put_item")
        key = self._key(TableName, Item)
        if ConditionExpression and "attribute_not_exists" in ConditionExpression and key in self.tables[TableName]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}}, "PutItem")
        self.tables[TableName][key] = Item
        return {}

    def get_item(self, TableName, Key):
        self.calls.append("get_item")
        item = self.tables[TableName].get(self._key(TableName, Key))
        return {"Item": item} if item else {}

    def query(self, TableName, ExpressionAttributeValues, **kwargs):
        self.calls.append("query")
        pk = ExpressionAttributeValues[":pk"]["S"]
        rows = [item for (p, s), item in sorted(self.tables[TableName].items(), key=lambda kv: (kv[0][0], kv[0][1] or "")) if p == pk]
        return {"Items": rows}

    def scan(self, TableName, **kwargs):
        self.calls.append("scan")
        return {"Items": list(self.tables[TableName].values())}


class BrokenDynamoDB:
    """Every call fails like an expired or denied session."""

    def __getattr__(self, name):
        def fail(**kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, name)
        return fail

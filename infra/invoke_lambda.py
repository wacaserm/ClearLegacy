"""Call the deployed ClearLegacy Lambda Function URL with a SigV4-signed request.

Usage: python infra/invoke_lambda.py morgan sample_data/01_morgan_discrepancies/planning_summary.pdf sample_data/01_morgan_discrepancies/account_records.pdf
Uses the credentials in your environment; the URL rejects unsigned requests.
"""

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-east-1"
FUNCTION = "clearlegacy-analyze"


def function_url() -> str:
    return boto3.client("lambda", region_name=REGION).get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"]


def invoke(client_id: str, paths: list[str], sign: bool = True) -> tuple[int, dict]:
    body = json.dumps({"clientId": client_id, "documents": [
        {"filename": Path(p).name, "contentBase64": base64.b64encode(Path(p).read_bytes()).decode()} for p in paths]})
    url = function_url()
    headers = {"content-type": "application/json"}
    if sign:
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(boto3.Session().get_credentials(), "lambda", REGION).add_auth(request)
        headers = dict(request.headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body.encode(), headers=headers, method="POST"), timeout=150) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as error:
        return error.code, {"error": error.read().decode()[:200]}


if __name__ == "__main__":
    start = time.perf_counter()
    status, result = invoke(sys.argv[1], sys.argv[2:])
    print(f"HTTP {status} in {time.perf_counter() - start:.1f}s")
    print(json.dumps(result, indent=2)[:4000])

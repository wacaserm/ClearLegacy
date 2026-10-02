"""AWS Lambda entry point: run ClearLegacy's analysis pipeline.

Request (Function URL POST body, or a direct invoke payload):
  {"clientId": "morgan",
   "documents": [{"filename": "planning_summary.pdf", "contentBase64": "..."}]}
Response: the same analysis JSON the app receives from core.pipeline.analyze.

Configured by infra/deploy_lambda.py (DynamoDB storage, S3, Textract, PII masking).
"""

import base64
import json

from core import pipeline

MAX_DOCUMENTS = 10


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    try:
        if isinstance(event, dict) and "body" in event:
            raw = event["body"] or "{}"
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            request = json.loads(raw)
        else:
            request = event or {}
        client_id = request.get("clientId")
        documents = request.get("documents") or []
        if not isinstance(client_id, str) or not client_id:
            return _response(400, {"error": "clientId is required"})
        if not isinstance(documents, list) or not documents or len(documents) > MAX_DOCUMENTS:
            return _response(400, {"error": f"send 1-{MAX_DOCUMENTS} documents"})
        uploads = [(base64.b64decode(d["contentBase64"]), str(d["filename"])) for d in documents]
    except (ValueError, KeyError, TypeError) as error:
        return _response(400, {"error": f"invalid request: {error}"})

    try:
        result = pipeline.analyze(client_id, uploads)
    except Exception as error:  # report, never crash the invocation
        return _response(500, {"status": "failed", "error": f"{type(error).__name__}: {error}"})
    return _response(200, result)

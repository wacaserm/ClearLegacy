"""Thin wrapper around the Bedrock Converse API that forces structured tool output.

Credentials come from the standard AWS environment variables; nothing is read
from or written to files here.
"""

import json
import logging
import os
import threading
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

log = logging.getLogger(__name__)

REGION = (
    os.environ.get("BEDROCK_REGION")
    or os.environ.get("AWS_REGION")
    or os.environ.get("AWS_DEFAULT_REGION")
    or "us-east-1"
)
MODEL_ID = os.environ.get("CLEARLEGACY_MODEL_ID", "us.anthropic.claude-sonnet-5")
FAST_MODEL_ID = os.environ.get(
    "CLEARLEGACY_FAST_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)

CREDENTIALS_EXPIRED_MSG = "AWS credentials expired: refresh them from the workshop page"
CREDENTIALS_MISSING_MSG = (
    "AWS credentials not found: copy AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and "
    "AWS_SESSION_TOKEN from the workshop page into the terminal that starts the app"
)
_MODEL_UNAVAILABLE_CODES = {"AccessDeniedException", "ResourceNotFoundException"}
_EXPIRED_CODES = {
    "ExpiredToken",
    "ExpiredTokenException",
    "UnrecognizedClientException",
    "InvalidSignatureException",
    "InvalidClientTokenId",
}


class BedrockError(RuntimeError):
    """Raised when a Bedrock call fails or returns an unusable response."""


class AWSCredentialsExpired(BedrockError):
    def __init__(self, message: str = CREDENTIALS_EXPIRED_MSG):
        super().__init__(message)


class AWSCredentialsMissing(AWSCredentialsExpired):
    """No credentials at all. Subclass so existing `except AWSCredentialsExpired` still catches it."""

    def __init__(self):
        super().__init__(CREDENTIALS_MISSING_MSG)


def credentials_error(exc: Exception) -> AWSCredentialsExpired:
    return AWSCredentialsMissing() if isinstance(exc, NoCredentialsError) else AWSCredentialsExpired()


def _model_hint(exc: ClientError, model_id: str) -> str:
    error = exc.response.get("Error", {})
    code, message = error.get("Code", ""), error.get("Message", "")
    lowered = message.lower()
    if code in _MODEL_UNAVAILABLE_CODES or "model identifier" in lowered or ("model" in lowered and "access" in lowered):
        return (
            f" Model '{model_id}' isn't available to this AWS account in {REGION}. "
            "Set CLEARLEGACY_MODEL_ID (or CLEARLEGACY_FAST_MODEL_ID) to a model enabled in the workshop account."
        )
    return ""


def is_credentials_error(exc: Exception) -> bool:
    if isinstance(exc, NoCredentialsError):
        return True
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") in _EXPIRED_CODES
    return False


# --------------------------------------------------------------------------- token usage and cost

# USD per 1M tokens (input, output). VERIFY before quoting: these are Anthropic's
# published first-party rates (Sonnet 5: $2/$10, Haiku 4.5: $1/$5). Amazon Bedrock is
# partner-priced and may differ; check https://aws.amazon.com/bedrock/pricing/ for
# on-demand cross-region inference rates in us-east-1.
PRICES_PER_MILLION = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Per-thread totals: Streamlit runs each session in its own thread, so concurrent
# analyses don't mix their counts.
_usage = threading.local()


def _record_usage(model_id: str, usage: dict) -> None:
    totals = getattr(_usage, "totals", None)
    if totals is None:
        totals = _usage.totals = {}
    entry = totals.setdefault(model_id, {"calls": 0, "inputTokens": 0, "outputTokens": 0})
    entry["calls"] += 1
    entry["inputTokens"] += int(usage.get("inputTokens", 0))
    entry["outputTokens"] += int(usage.get("outputTokens", 0))


def usage_snapshot() -> dict:
    return {model: dict(entry) for model, entry in (getattr(_usage, "totals", None) or {}).items()}


def _price(model_id: str):
    for key, price in PRICES_PER_MILLION.items():
        if key in model_id:
            return price
    return None


def usage_since(before: dict) -> dict:
    """Token usage and estimated cost (USD) since a usage_snapshot()."""
    models, total = {}, 0.0
    for model, entry in usage_snapshot().items():
        base = before.get(model, {})
        delta = {k: entry[k] - base.get(k, 0) for k in ("calls", "inputTokens", "outputTokens")}
        if not delta["calls"]:
            continue
        price = _price(model)
        cost = (delta["inputTokens"] * price[0] + delta["outputTokens"] * price[1]) / 1e6 if price else None
        models[model] = {**delta, "estimatedCostUSD": round(cost, 5) if cost is not None else None}
        total += cost or 0.0
    return {"models": models, "estimatedCostUSD": round(total, 5), "pricesNote": "estimate; verify Bedrock rates"}


def merge_usage(first: dict, second: dict) -> dict:
    models = {m: dict(v) for m, v in (first or {}).get("models", {}).items()}
    for model, entry in (second or {}).get("models", {}).items():
        target = models.setdefault(model, {"calls": 0, "inputTokens": 0, "outputTokens": 0, "estimatedCostUSD": 0.0})
        for key in ("calls", "inputTokens", "outputTokens"):
            target[key] += entry[key]
        target["estimatedCostUSD"] = round((target.get("estimatedCostUSD") or 0) + (entry.get("estimatedCostUSD") or 0), 5)
    total = round(sum(m.get("estimatedCostUSD") or 0 for m in models.values()), 5)
    return {"models": models, "estimatedCostUSD": total, "pricesNote": "estimate; verify Bedrock rates"}


@lru_cache(maxsize=None)
def get_client(service: str = "bedrock-runtime"):
    """Cached boto3 client (also used for Textract)."""
    config = Config(
        region_name=REGION,
        read_timeout=120,
        connect_timeout=10,
        retries={"max_attempts": 5, "mode": "adaptive"},
    )
    return boto3.client(service, config=config)


def call_tool(
    system: str,
    user_text: str,
    tool_name: str,
    tool_description: str,
    schema: dict,
    model_id: str = MODEL_ID,
    max_tokens: int = 4096,
) -> dict:
    """Call Bedrock forcing a single tool and return the tool's input dict.

    Never passes temperature (Sonnet 5 rejects it); only maxTokens is set.
    """
    try:
        response = get_client().converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"maxTokens": max_tokens},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool_name,
                            "description": tool_description,
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": tool_name}},
            },
        )
    except (ClientError, NoCredentialsError) as exc:
        if is_credentials_error(exc):
            raise credentials_error(exc) from exc
        raise BedrockError(f"Bedrock call to {model_id} failed: {exc}.{_model_hint(exc, model_id)}") from exc
    except BotoCoreError as exc:  # timeouts, connection errors
        raise BedrockError(f"Could not reach Bedrock ({model_id}): {exc}") from exc

    _record_usage(model_id, response.get("usage") or {})
    stop_reason = response.get("stopReason")
    if stop_reason == "max_tokens":
        # A truncated tool input may be partial; never treat it as complete.
        raise BedrockError(
            f"Model {model_id} hit maxTokens={max_tokens} before finishing '{tool_name}'; "
            "increase max_tokens or send less text"
        )
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "toolUse" in block and block["toolUse"].get("name") == tool_name:
            tool_input = block["toolUse"].get("input")
            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except json.JSONDecodeError:
                    tool_input = None
            if not isinstance(tool_input, dict):
                raise BedrockError(f"Model {model_id} returned malformed '{tool_name}' input")
            return tool_input

    raise BedrockError(
        f"Model {model_id} did not return a '{tool_name}' toolUse block (stopReason={stop_reason})"
    )

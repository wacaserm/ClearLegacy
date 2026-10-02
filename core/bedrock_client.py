"""Thin wrapper around the Bedrock Converse API that forces structured tool output.

Credentials come from the standard AWS environment variables; nothing is read
from or written to files here.
"""

import json
import logging
import os
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

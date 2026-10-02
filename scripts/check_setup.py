"""Check that this machine can run ClearLegacy, and say how to fix anything missing.

Usage: python scripts/check_setup.py
Makes two tiny Bedrock calls (a few tokens each) to confirm model access.
"""

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

problems = 0


def report(ok, label, fix=""):
    global problems
    print(f"[{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        problems += 1
        if fix:
            print(f"       -> {fix}")
    return ok


def main():
    report(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Use Python 3.10 or newer (the team uses 3.12).")

    for module in ("streamlit", "boto3", "pypdf", "docx", "reportlab", "pytest"):
        try:
            importlib.import_module(module)
            report(True, f"package {module}")
        except ImportError:
            report(False, f"package {module}", "Run: python -m pip install -r requirements.txt")

    try:
        from core import store

        clients = store.get_clients()
        report(bool(clients), f"client records ({len(clients)} households in data/clients.json)")
    except Exception as error:
        report(False, "client records", f"data/clients.json could not be loaded: {error}")

    try:
        from core.document_reader import read_document

        sample = ROOT / "sample_data" / "01_morgan_discrepancies" / "planning_summary.docx"
        document = read_document(sample.read_bytes(), sample.name)
        report(bool(document.get("sections")), "DOCX reading (sample planning summary)")
    except Exception as error:
        report(False, "DOCX reading", f"{error}")

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

    from core import bedrock_client as bc

    try:
        identity = boto3.client("sts", region_name=bc.REGION).get_caller_identity()
        report(True, f"AWS credentials ({identity['Arn'].split('/')[-2] if '/' in identity['Arn'] else 'ok'}, region {bc.REGION})")
    except NoCredentialsError:
        report(False, "AWS credentials", bc.CREDENTIALS_MISSING_MSG)
        return
    except (ClientError, BotoCoreError) as error:
        report(False, "AWS credentials", f"{bc.CREDENTIALS_EXPIRED_MSG} ({error})")
        return

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    for label, model_id in (("main model", bc.MODEL_ID), ("fast model", bc.FAST_MODEL_ID)):
        try:
            bc.call_tool("Reply using the tool.", "Say ok.", "reply", "Reply.", schema, model_id=model_id, max_tokens=64)
            report(True, f"Bedrock {label} {model_id}")
        except bc.BedrockError as error:
            report(False, f"Bedrock {label} {model_id}", str(error))


if __name__ == "__main__":
    main()
    print("\nAll checks passed. Start the app with: python -m streamlit run app.py" if not problems
          else f"\n{problems} problem(s) found. Fix them and run this check again.")
    sys.exit(1 if problems else 0)

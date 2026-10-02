"""Check that this machine can run ClearLegacy, and say how to fix anything missing.

Usage: python scripts/check_setup.py
Makes two tiny Bedrock calls, one 1-pixel Textract call and one short Comprehend call
(fractions of a cent) to confirm access, and reports which AWS flags are active.
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
        identity = boto3.client("sts", region_name=bc.REGION).get_caller_identity()  # noqa: F841 (used below)
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

    check_aws_services(boto3, ClientError, BotoCoreError, identity["Account"])


def info(label):
    print(f"[ -- ] {label}")


def check_aws_services(boto3, ClientError, BotoCoreError, account):
    """Optional services: a missing resource is only a FAIL when a flag needs it."""
    import base64

    from core import config

    flags = config.summary()
    print(f"\nActive flags: storage={flags['storage']} s3={int(flags['s3'])} textract={int(flags['textract'])} "
          f"pii_masking={int(flags['piiMasking'])} bucket={flags['bucket'] or '(not set)'} "
          f"table_prefix={flags['tablePrefix']}")
    region = config.REGION

    tiny_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    try:
        boto3.client("textract", region_name=region).detect_document_text(Document={"Bytes": tiny_png})
        report(True, "Amazon Textract (DetectDocumentText)")
    except (ClientError, BotoCoreError) as error:
        (report if flags["textract"] else lambda ok, label, fix="": info(f"{label} unavailable (flag off)"))(
            False, "Amazon Textract", f"{error} (set CLEARLEGACY_USE_TEXTRACT=0 to skip OCR)")

    bucket = flags["bucket"] or f"clearlegacy-{account}-{region}"
    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_bucket(Bucket=bucket)
        encryption = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][0][
            "ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
        block = all(s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values())
        report(bool(encryption) and block, f"S3 bucket {bucket} (encryption {encryption}, public access blocked: {block})",
               "Run: python infra/setup_aws.py")
    except (ClientError, BotoCoreError):
        if flags["s3"] or flags["bucket"]:
            report(False, f"S3 bucket {bucket}", "Run: python infra/setup_aws.py")
        else:
            info(f"S3 bucket {bucket} not found (only needed with CLEARLEGACY_USE_S3=1 or multi-page OCR)")

    dynamodb = boto3.client("dynamodb", region_name=region)
    missing = []
    for kind in ("clients", "accounts", "findings", "audit"):
        try:
            dynamodb.describe_table(TableName=config.table_name(kind))
        except (ClientError, BotoCoreError):
            missing.append(config.table_name(kind))
    if not missing:
        seeded = dynamodb.scan(TableName=config.table_name("clients"), Select="COUNT")["Count"]
        report(seeded > 0 or flags["storage"] != "dynamodb",
               f"DynamoDB tables {config.table_prefix()}* ({seeded} clients seeded)", "Run: python infra/seed_dynamodb.py")
    elif flags["storage"] == "dynamodb":
        report(False, f"DynamoDB tables missing: {', '.join(missing)}", "Run: python infra/setup_aws.py")
    else:
        info("DynamoDB tables not found (only needed with CLEARLEGACY_STORAGE=dynamodb)")

    try:
        boto3.client("comprehend", region_name=region).detect_pii_entities(Text="Call 555-123-4567", LanguageCode="en")
        report(True, "Amazon Comprehend (DetectPiiEntities)")
    except (ClientError, BotoCoreError) as error:
        if flags["piiMasking"]:
            report(False, "Amazon Comprehend", f"{error} (masking falls back to local patterns)")
        else:
            info("Amazon Comprehend unavailable (only needed with CLEARLEGACY_PII_MASKING=1)")

    try:
        url = boto3.client("lambda", region_name=region).get_function_url_config(FunctionName="clearlegacy-analyze")["FunctionUrl"]
        info(f"Lambda clearlegacy-analyze deployed: {url} (IAM auth)")
    except (ClientError, BotoCoreError):
        info("Lambda clearlegacy-analyze not deployed (optional: python infra/deploy_lambda.py)")


if __name__ == "__main__":
    main()
    print("\nAll checks passed. Start the app with: python -m streamlit run app.py" if not problems
          else f"\n{problems} problem(s) found. Fix them and run this check again.")
    sys.exit(1 if problems else 0)

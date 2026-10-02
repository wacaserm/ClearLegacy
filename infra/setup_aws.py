"""Create (or verify) ClearLegacy's pay-per-use AWS resources. Safe to rerun.

Creates in us-east-1:
  - S3 bucket clearlegacy-<account-id>-us-east-1: SSE-S3 (AES256) default
    encryption, Block Public Access fully on, versioning on.
  - DynamoDB tables (PAY_PER_REQUEST): <prefix>clients, <prefix>accounts,
    <prefix>findings, <prefix>audit.

Usage:
  python infra/setup_aws.py              # create or verify
  python infra/setup_aws.py --teardown   # delete everything (asks first)

Credentials come from environment variables only.
"""

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402

REGION = "us-east-1"

# name suffix -> (partition key, sort key or None)
TABLES = {
    "clients": ("clientId", None),
    "accounts": ("clientId", "accountId"),
    "findings": ("clientId", "findingId"),
    "audit": ("clientId", "sk"),  # sk = "<timestamp>#<auditId>"
}


def bucket_name(account_id: str) -> str:
    return f"clearlegacy-{account_id}-{REGION}"


def ensure_bucket(s3, name: str) -> None:
    try:
        s3.head_bucket(Bucket=name)
        print(f"[exists ] s3://{name}")
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        s3.create_bucket(Bucket=name)  # us-east-1 takes no LocationConstraint
        s3.get_waiter("bucket_exists").wait(Bucket=name)
        print(f"[created] s3://{name}")

    s3.put_public_access_block(
        Bucket=name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    print("          block public access: on | default encryption: AES256 | versioning: on")


def ensure_table(dynamodb, name: str, pk: str, sk: str | None) -> None:
    try:
        status = dynamodb.describe_table(TableName=name)["Table"]["TableStatus"]
        print(f"[exists ] dynamodb {name} ({status})")
        return
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    keys = [{"AttributeName": pk, "KeyType": "HASH"}]
    attrs = [{"AttributeName": pk, "AttributeType": "S"}]
    if sk:
        keys.append({"AttributeName": sk, "KeyType": "RANGE"})
        attrs.append({"AttributeName": sk, "AttributeType": "S"})
    dynamodb.create_table(
        TableName=name,
        KeySchema=keys,
        AttributeDefinitions=attrs,
        BillingMode="PAY_PER_REQUEST",
        Tags=[{"Key": "project", "Value": "clearlegacy"}],
    )
    dynamodb.get_waiter("table_exists").wait(TableName=name)
    print(f"[created] dynamodb {name} (on-demand)")


def teardown(s3, dynamodb, name: str) -> None:
    answer = input(f"Delete s3://{name} (all object versions) and the {config.table_prefix()}* tables? Type 'delete': ")
    if answer.strip() != "delete":
        print("Cancelled.")
        return
    try:
        bucket = boto3.resource("s3", region_name=REGION).Bucket(name)
        bucket.object_versions.delete()
        bucket.delete()
        print(f"[deleted] s3://{name}")
    except ClientError as error:
        print(f"[skip   ] s3://{name}: {error.response['Error']['Code']}")
    for kind in TABLES:
        table = config.table_name(kind)
        try:
            dynamodb.delete_table(TableName=table)
            print(f"[deleted] dynamodb {table}")
        except ClientError as error:
            print(f"[skip   ] dynamodb {table}: {error.response['Error']['Code']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--teardown", action="store_true", help="delete the bucket and tables (asks for confirmation)")
    args = parser.parse_args()

    account_id = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    name = config.bucket() or bucket_name(account_id)
    s3 = boto3.client("s3", region_name=REGION)
    dynamodb = boto3.client("dynamodb", region_name=REGION)

    if args.teardown:
        teardown(s3, dynamodb, name)
        return

    ensure_bucket(s3, name)
    for kind, (pk, sk) in TABLES.items():
        ensure_table(dynamodb, config.table_name(kind), pk, sk)

    print("\nTo use these resources, set in the terminal that runs the app:")
    print(f'  export CLEARLEGACY_BUCKET="{name}"')
    print('  export CLEARLEGACY_STORAGE="dynamodb"')
    print('  export CLEARLEGACY_USE_S3="1"')
    print('  export CLEARLEGACY_USE_TEXTRACT="1"')
    print('  export CLEARLEGACY_PII_MASKING="1"')
    print("Then load the client records: python infra/seed_dynamodb.py")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        code = error.response["Error"]["Code"]
        print(f"AWS refused the request ({code}): {error.response['Error'].get('Message', '')}")
        sys.exit(1)

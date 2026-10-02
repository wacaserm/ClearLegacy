"""Deploy ClearLegacy's analysis pipeline to AWS Lambda behind a Function URL (IAM auth).

Why a Function URL instead of API Gateway: HTTP APIs time out at 30 seconds and
one analysis takes about 25-30 seconds. Function URLs allow the full Lambda
timeout. AuthType AWS_IAM keeps the endpoint private (requests must be SigV4-signed).

Usage:
  python infra/deploy_lambda.py              # build, create or update
  python infra/deploy_lambda.py --teardown   # delete function, URL, and role (asks first)

Requires infra/setup_aws.py to have run (bucket and tables). Pay-per-use only.
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

REGION = "us-east-1"
FUNCTION = "clearlegacy-analyze"
ROLE = "clearlegacy-lambda-role"
RUNTIME = "python3.12"
PACKAGES = ["boto3", "botocore", "pypdf", "python-docx"]  # bundled so Converse/tool use is current


def build_zip() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp) / "build"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(build),
             "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.12",
             "--only-binary=:all:", *PACKAGES],
            check=True,
        )
        shutil.copytree(ROOT / "core", build / "core", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "prompts", build / "prompts")
        (build / "data").mkdir()
        shutil.copy(ROOT / "data" / "clients.json", build / "data" / "clients.json")
        shutil.copy(ROOT / "infra" / "lambda_function.py", build / "lambda_function.py")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(build.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(build))
        return buffer.getvalue()


def policy(account: str, bucket: str) -> dict:
    tables = [f"arn:aws:dynamodb:{REGION}:{account}:table/{config.table_prefix()}*"]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": f"arn:aws:logs:{REGION}:{account}:*"},
            # Cross-region inference profiles route to several regions' foundation models.
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel"],
             "Resource": ["arn:aws:bedrock:*::foundation-model/anthropic.*",
                          f"arn:aws:bedrock:*:{account}:inference-profile/us.anthropic.*"]},
            {"Effect": "Allow", "Action": ["textract:DetectDocumentText", "textract:StartDocumentTextDetection",
                                           "textract:GetDocumentTextDetection"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["comprehend:DetectPiiEntities"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
             "Resource": f"arn:aws:s3:::{bucket}/*"},
            {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan"],
             "Resource": tables},
        ],
    }


def ensure_role(iam, account: str, bucket: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
        print(f"[exists ] role {ROLE}")
        new = False
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="ClearLegacy analysis Lambda (least privilege)")["Role"]["Arn"]
        print(f"[created] role {ROLE}")
        new = True
    iam.put_role_policy(RoleName=ROLE, PolicyName="clearlegacy-analyze", PolicyDocument=json.dumps(policy(account, bucket)))
    if new:
        time.sleep(12)  # new roles take a few seconds before Lambda can assume them
    return arn


def deploy() -> None:
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    bucket = config.bucket() or f"clearlegacy-{account}-{REGION}"
    lam = boto3.client("lambda", region_name=REGION)
    role_arn = ensure_role(boto3.client("iam"), account, bucket)

    print("building package (Linux wheels)...")
    package = build_zip()
    print(f"package size: {len(package) / 1e6:.1f} MB")
    environment = {"Variables": {
        "CLEARLEGACY_STORAGE": "dynamodb", "CLEARLEGACY_USE_S3": "1", "CLEARLEGACY_USE_TEXTRACT": "1",
        "CLEARLEGACY_PII_MASKING": "1", "CLEARLEGACY_BUCKET": bucket, "CLEARLEGACY_TABLE_PREFIX": config.table_prefix(),
        "CLEARLEGACY_RUNTIME_DIR": "/tmp/clearlegacy-runtime",
    }}
    settings = dict(Runtime=RUNTIME, Role=role_arn, Handler="lambda_function.handler", Timeout=120,
                    MemorySize=1024, Environment=environment)
    try:
        lam.get_function(FunctionName=FUNCTION)
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=package)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
        lam.update_function_configuration(FunctionName=FUNCTION, **settings)
        print(f"[updated] function {FUNCTION}")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        for attempt in range(5):
            try:
                lam.create_function(FunctionName=FUNCTION, Code={"ZipFile": package}, **settings,
                                    Tags={"project": "clearlegacy"})
                break
            except ClientError as create_error:
                if "cannot be assumed" not in str(create_error) or attempt == 4:
                    raise
                time.sleep(5)
        print(f"[created] function {FUNCTION}")
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)

    try:
        url = lam.get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"]
    except ClientError:
        url = lam.create_function_url_config(FunctionName=FUNCTION, AuthType="AWS_IAM")["FunctionUrl"]
    print(f"[ready  ] {url}  (AuthType AWS_IAM: requests must be SigV4-signed)")


def teardown() -> None:
    if input(f"Delete Lambda {FUNCTION}, its URL, and role {ROLE}? Type 'delete': ").strip() != "delete":
        print("Cancelled.")
        return
    lam = boto3.client("lambda", region_name=REGION)
    iam = boto3.client("iam")
    for step, call in [("function URL", lambda: lam.delete_function_url_config(FunctionName=FUNCTION)),
                       ("function", lambda: lam.delete_function(FunctionName=FUNCTION)),
                       ("role policy", lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName="clearlegacy-analyze")),
                       ("role", lambda: iam.delete_role(RoleName=ROLE))]:
        try:
            call()
            print(f"[deleted] {step}")
        except ClientError as error:
            print(f"[skip   ] {step}: {error.response['Error']['Code']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args()
    try:
        teardown() if args.teardown else deploy()
    except ClientError as error:
        print(f"AWS refused the request ({error.response['Error']['Code']}): {error.response['Error'].get('Message', '')}")
        sys.exit(1)

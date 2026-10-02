"""Role 1 demo: extract facts from every fixture, explain a sample finding, run the AI conflict pass.

Usage: python scripts/run_role1_demo.py
Requires AWS credentials in environment variables (region us-east-1).
"""

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.bedrock_client import AWSCredentialsExpired  # noqa: E402
from core.explain import explain, find_additional_conflicts  # noqa: E402
from core.extract import extract_document  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
DOCS = [
    ("johnson_will.txt", "will"),
    ("johnson_trust.txt", "trust"),
    ("johnson_poa.txt", "poa"),
    ("clean_will.txt", "will"),
    ("pdf/johnson_will.pdf", "will"),
    ("pdf/johnson_trust.pdf", "trust"),
    ("pdf/johnson_poa.pdf", "poa"),
]


def show(title, obj):
    print(f"\n=== {title} ===")
    print(json.dumps(obj, indent=2))


def timed(label, fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    print(f"[timing] {label}: {time.perf_counter() - start:.1f}s")
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("botocore").setLevel(logging.WARNING)

    results = {}
    for rel, doc_type in DOCS:
        facts = timed(f"extract {rel}", extract_document, FIXTURES / rel, doc_type)
        results[rel] = facts
        show(f"{rel} facts", {k: v for k, v in facts.items() if k != "dropped"})
        show(f"{rel} dropped", facts["dropped"])

    data = json.loads((FIXTURES / "johnson_accounts.json").read_text())
    will = results["johnson_will.txt"]
    residuary = next(
        (a for a in will["assets"] if "brokerage" in a["description"].lower()), None
    )
    sample = {
        "findingId": "F-001",
        "severity": "high",
        "title": "Will splits estate among three children, but brokerage TOD names ex-wife",
        "evidence": [
            {
                "source": "document",
                "docType": "will",
                "page": residuary["page"] if residuary else 1,
                "quote": residuary["quote"] if residuary
                else "My brokerage account at LPL Financial shall pass as part of my residuary estate.",
            },
            {
                "source": "document",
                "docType": "will",
                "page": 1,
                "quote": "in equal shares to my children, Emily Johnson, David Johnson and Sarah Johnson",
            },
            {
                "source": "account",
                "docType": None,
                "page": None,
                "quote": "Brokerage ...4471 TOD beneficiary: Linda Johnson (ex-wife), set 2009",
            },
        ],
    }
    show("sample finding", sample)
    show("explain(sample)", timed("explain (fast model)", explain, sample))

    johnson = [results[k] for k in ("johnson_will.txt", "johnson_trust.txt", "johnson_poa.txt")]
    extra = timed(
        "find_additional_conflicts", find_additional_conflicts, johnson, data["client"], data["accounts"]
    )
    show("additional AI findings (verified)", extra)


if __name__ == "__main__":
    try:
        main()
    except AWSCredentialsExpired as exc:
        print(exc)
        sys.exit(1)

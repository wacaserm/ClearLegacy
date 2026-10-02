"""Role 1 demo: extract and validate facts from fixtures and sample households,
explain a sample finding, then run the optional AI conflict pass on Johnson.

Usage: python scripts/run_role1_demo.py
Requires AWS credentials in environment variables (region us-east-1).
About 17 Bedrock calls per run.
"""

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.bedrock_client import AWSCredentialsExpired  # noqa: E402
from core.assistant import answer_question  # noqa: E402
from core.explain import explain, find_additional_conflicts, summarize_case  # noqa: E402
from core.extract import extract_document  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SAMPLES = ROOT / "sample_data"

JOHNSON = [
    (FIXTURES / "pdf" / "johnson_will.pdf", "will", "johnson-will-2019"),
    (FIXTURES / "pdf" / "johnson_trust.pdf", "trust", "johnson-trust-2021"),
    (FIXTURES / "pdf" / "johnson_poa.pdf", "poa", "johnson-poa-2014"),
    (FIXTURES / "pdf" / "johnson_intentions.pdf", "planning_summary", "johnson-plan-2026"),
]
OTHERS = [(FIXTURES / "clean_will.txt", "will", "lopez-will-2023")] + [
    (path, "account_records" if path.stem == "account_records" else "planning_summary",
     f"{path.parent.name.split('_')[1]}-{path.stem.replace('_', '-')}")
    for path in sorted(SAMPLES.glob("*/*.pdf"))
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
    for path, doc_type, source_id in JOHNSON + OTHERS:
        facts = timed(f"extract {path.relative_to(ROOT)}", extract_document, path, doc_type, source_id)
        results[source_id] = facts
        show(f"{source_id} facts", facts["facts"])
        show(f"{source_id} warnings", facts["warnings"])

    data = json.loads((FIXTURES / "johnson_accounts.json").read_text())
    plan = results["johnson-plan-2026"]
    intention = next(
        (f for f in plan["facts"] if f["field"] == "intended_beneficiary" and "4471" in (f.get("accountRef") or "")),
        None,
    )
    sample = {
        "findingId": "F1",
        "priority": "high",
        "title": "Stated intention for DEMO-JOHNSON-4471 differs from its TOD designation",
        "evidence": [
            {
                "sourceType": "document",
                "sourceId": "johnson-plan-2026",
                "location": intention["location"] if intention else "page 1",
                "quote": intention["quote"] if intention else
                "For brokerage account DEMO-JOHNSON-4471, I want my three children, Emily, David and Sarah, to receive equal shares.",
            },
            {
                "sourceType": "account",
                "sourceId": "DEMO-JOHNSON-4471",
                "field": "todBeneficiaries",
                "value": "Linda Johnson 100%, recorded 2009-05-11",
            },
        ],
    }
    show("sample finding", sample)
    explained = timed("explain (fast model)", explain, sample)
    show("explain(sample)", explained)

    johnson = [results[source_id] for _, _, source_id in JOHNSON]
    extra = timed(
        "find_additional_conflicts", find_additional_conflicts, johnson, data["client"], data["accounts"]
    )
    show("additional AI findings (verified)", extra)

    findings = [{**sample, **explained}] + extra
    show("summarize_case", timed("summarize_case (fast model)", summarize_case, data["client"], findings))

    history = []
    for question in [
        "Which accounts aren't covered by the trust?",
        "Who would act for Robert now that Thomas has died?",
        "What is Robert's Social Security number?",
    ]:
        reply = timed(f"answer_question: {question}", answer_question,
                      question, johnson, data["client"], data["accounts"], findings, history)
        show(f"Q: {question}", reply)
        history.append({"question": question, "answer": reply["answer"]})


if __name__ == "__main__":
    try:
        main()
    except AWSCredentialsExpired as exc:
        print(exc)
        sys.exit(1)

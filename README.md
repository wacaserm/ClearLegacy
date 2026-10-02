# ClearLegacy
## Role 1: AI extraction

The AI only **extracts facts** and **explains findings**. Comparing documents to accounts is done by plain Python rules in `core/rules.py` (Role 2). Every extracted fact carries a `page` and a verbatim `quote`, and any fact whose quote can't be found in the source text is dropped. This is our guard against hallucinated conflicts.

### Functions

| Function | Input | Output |
|---|---|---|
| `core.extract.read_pdf(path)` | `.pdf`, or `.txt` with `=== PAGE N ===` separators | `[{"page": 1, "text": "..."}]`. Scanned single-page PDFs are OCR'd with Textract. Scanned pages in multi-page PDFs come back as `""` with a warning. |
| `core.extract.extract_facts(pages, doc_type)` | pages from `read_pdf`, `doc_type` in `will\|trust\|poa\|beneficiary_form\|other` | raw facts dict (below), from Sonnet 5 |
| `core.extract.validate_facts(facts, pages)` | facts + pages | facts with unverifiable items removed, wrong page numbers corrected, plus `"dropped": [{"field", "item", "reason"}]` |
| `core.extract.extract_document(path, doc_type)` | file path | read + extract + validate, plus `"source": "<filename>"` |
| `core.explain.explain(finding)` | finding dict (below) | `{"explanation": "<=2 sentences", "recommendedAction": "1 sentence"}` (Haiku 4.5) |
| `core.explain.find_additional_conflicts(facts_list, client, accounts)` | list of `extract_document` outputs, client dict, accounts list | list of findings, all `severity: "review"`. Evidence must match already-verified fact quotes or exact account values, or the finding is dropped. |

Facts format:

```json
{
  "docType": "will",
  "dateSigned":     {"value": "2019-03-14", "page": 2, "quote": "..."},
  "governingState": {"value": "CA", "page": 2, "quote": "..."},
  "people": [{"name": "Emily Johnson", "relationship": "daughter", "role": "beneficiary",
              "share": "equal shares", "page": 1, "quote": "..."}],
  "assets": [{"description": "LPL brokerage account", "disposition": "residuary estate",
              "page": 1, "quote": "..."}],
  "dropped": [],
  "source": "johnson_will.txt"
}
```

`role` is one of `beneficiary|executor|trustee|successor_trustee|poa_agent|guardian|other`. When the date or state is missing, `value`, `page` and `quote` are all `null`.

Finding format (input to `explain`, output of `find_additional_conflicts`):

```json
{"findingId": "F-001", "severity": "high", "title": "...",
 "evidence": [{"source": "document", "docType": "will", "page": 1, "quote": "..."},
              {"source": "account", "docType": null, "page": null, "quote": "..."}]}
```

### Configuration

- AWS credentials come from environment variables only (region `us-east-1`). Never commit them.
- `CLEARLEGACY_MODEL_ID` (default `us.anthropic.claude-sonnet-5`) and `CLEARLEGACY_FAST_MODEL_ID` (default `us.anthropic.claude-haiku-4-5-20251001-v1:0`).
- Expired or missing credentials raise `AWSCredentialsExpired` with the message "AWS credentials expired: refresh them from the workshop page".

### Running

```bash
pip install -r requirements.txt
python -m pytest tests                  # validator tests, no AWS needed
python scripts/make_fixture_pdfs.py     # regenerate tests/fixtures/pdf/ from the .txt fixtures
python scripts/run_role1_demo.py        # live Bedrock demo over all fixtures, with timings
```

All fixtures in `tests/fixtures/` are fictional.

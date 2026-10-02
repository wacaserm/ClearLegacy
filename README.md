# ClearLegacy

## Running ClearLegacy

Open a PowerShell terminal in the ClearLegacy repository folder.

### 1. Activate your virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If you have not created the environment yet, follow the Python environment
setup section first.

### 2. Install dependencies

Run this on your first setup or whenever `requirements.txt` changes:

```powershell
python -m pip install -r requirements.txt
```

### 3. Start the app

```powershell
python -m streamlit run app.py
```

Streamlit will display a local URL, usually `http://localhost:8501`.
Open that URL in your browser if it does not open automatically.

Keep the terminal running while using the app. To stop it, press **Ctrl+C**.

### Using the starter app

1. Review or edit the sample client planning summary.
2. Review or edit the beneficiary record.
3. Click **Analyze records**.

The starter version displays a placeholder message.
AI analysis will work after the Amazon Bedrock integration is connected.

## Project guide

See [the ClearLegacy project guide](docs/PROJECT_GUIDE.md)
for scope, architecture, team responsibilities, and demo expectations.

### Troubleshooting

- **`app.py` not found:** Make sure your terminal is in the repository folder.
- **`No module named streamlit`:** Activate the correct environment and
  install the dependencies.
- **Activation blocked:** Launch using the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Python environment setup

Use a separate virtual environment for ClearLegacy. Each teammate creates
their own local `.venv`; it is excluded from Git.

### Windows PowerShell

From the ClearLegacy repository folder, check your Python version:

```powershell
python --version
```

We are developing with Python 3.12.10.

If another project's virtual environment is active, deactivate it:

```powershell
deactivate
```

Create ClearLegacy's environment once:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Confirm that Python is using the correct environment:

```powershell
python -c "import sys; print(sys.executable)"
```

The path should end in `ClearLegacy\.venv\Scripts\python.exe`.
The `(.venv)` prompt alone does not confirm which project's environment is active.

Install the project dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the app:

```powershell
python -m streamlit run app.py
```

### Returning to the project

Activate the existing environment and launch the app:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

You do not need to recreate `.venv` each time.

### Troubleshooting

- If `py` is not recognized, use `python` instead.
- If Python points to another project's `.venv`, deactivate that environment
  and activate ClearLegacy's.
- If activation is blocked, run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Never commit `.venv`, AWS credentials, or secret configuration files.
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

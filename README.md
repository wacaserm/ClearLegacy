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

Follows the shared contracts in the project guide. The AI only **extracts facts** and **explains findings**. Comparison is done by Python rules in `core/rules.py` (Role 2). Every fact carries a `location` and a verbatim `quote`, and `core/validation.validate_facts` excludes any fact whose quote isn't in the document (it becomes a warning).

### Functions

| Function | Input | Output |
|---|---|---|
| `core.extract.extract_facts(document)` | document shape from `core/document_reader.read_document` | `{sourceId, docType, facts, warnings}` (not yet validated) |
| `core.validation.validate_facts(facts, document)` | facts + the same document | unsupported facts removed and added to `warnings` as `{"code": "unsupported_fact", ...}`, wrong locations corrected |
| `core.explain.explain(finding)` | guide finding (`findingId, priority, title, evidence`) | `{"explanation": "<=2 sentences", "recommendedAction": "1 sentence"}` (Haiku 4.5) |
| `core.explain.find_additional_conflicts(facts_list, client, accounts)` | validated facts, client dict, accounts list | optional extra findings, all `priority: "review"`. Every evidence item must match a validated fact quote or an actual account field value, or the finding is dropped. |
| `core.extract.load_document(path, doc_type, source_id)` | local `.pdf` or `.txt` (`=== PAGE N ===` separators) | the shared document shape, a stand-in until Role 3's reader is ready (no DOCX yet) |
| `core.extract.extract_document(path, doc_type, source_id)` | local file | load + extract + validate, for scripts |

An empty document returns no facts and a `no_readable_text` warning without calling Bedrock.

### Fact shape

```json
{"field": "intended_beneficiary", "value": "Casey Morgan", "location": "page 1",
 "quote": "I want Casey Morgan to receive 100% as primary beneficiary of my IRA DEMO-MORGAN-IRA.",
 "accountRef": "DEMO-MORGAN-IRA", "tier": "primary", "allocation": "100%",
 "relationship": "spouse", "asOf": null}
```

The extra keys (`accountRef`, `tier`, `allocation`, `relationship`, `asOf`) are always present and `null` when not stated.

`field` is one of: `document_id`, `document_date`, `snapshot_date`, `governing_state`, `client_name`, `family_member`, `intended_beneficiary` (account-specific intention), `intentional_exclusion`, `residuary_beneficiary` (general will or trust clause, never account-specific), `executor`, `alternate_executor`, `trustee`, `successor_trustee`, `poa_agent`, `successor_poa_agent`, `guardian`, `trust_owned_account`, `account_beneficiary` (designation on record), `account_registration`, `account_owner`, `missing_information`, `unspecified_intention`. Definitions are in `prompts/extraction.txt`.

`docType` is one of: `will`, `trust`, `poa`, `planning_summary`, `account_records`, `beneficiary_form`, `other`.

### Prompts

`prompts/extraction.txt`, `prompts/explanation.txt` and `prompts/conflicts.txt` are loaded at import. Document text is treated as data, never as instructions.

### Configuration and limits

- AWS credentials come from environment variables only (region `us-east-1`). Never commit them.
- `CLEARLEGACY_MODEL_ID` (default `us.anthropic.claude-sonnet-5`) and `CLEARLEGACY_FAST_MODEL_ID` (default `us.anthropic.claude-haiku-4-5-20251001-v1:0`).
- Expired or missing credentials raise `AWSCredentialsExpired`: "AWS credentials expired: refresh them from the workshop page".
- Cost per call: one Bedrock call per document extraction, one per `explain`, one for `find_additional_conflicts`. Each document takes about 6–11 seconds and a few thousand tokens.
- Workshop quotas are far above this (Sonnet 5: 6M tokens per minute; Haiku 4.5: 10,000 requests per minute; Textract: 25 per second).
- The client retries throttled calls with adaptive backoff (up to 5 attempts).
- In Streamlit, only call Bedrock on a button press and keep results in `st.session_state`, so reruns don't repeat calls.

### Running

```bash
pip install -r requirements.txt
python -m pytest tests                  # validation and evidence tests, no AWS needed
python scripts/make_fixture_pdfs.py     # regenerate tests/fixtures/pdf/ from the .txt fixtures
python scripts/run_role1_demo.py        # live demo: Johnson fixtures + sample_data PDFs (~13 Bedrock calls)
```

All fixtures are fictional demonstration summaries, not legal documents.

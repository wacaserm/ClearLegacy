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

The app sends the two summaries to Amazon Bedrock and displays the extracted,
source-grounded facts. Full reconciliation remains dependent on the validation,
rules, and explanation modules.

## Role 3: AWS and integration

The integration layer is responsible for document reading, JSON runtime storage,
Bedrock extraction wiring, and pipeline integration. The current prototype uses
fictional sample data and does not provision AWS resources.

### macOS/Linux setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure the workshop AWS credentials in the same terminal used to start the
app. Temporary credentials require all three values:

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
export AWS_REGION="us-east-1"
```

Verify the session before starting Streamlit:

```bash
aws sts get-caller-identity --region us-east-1
python -m streamlit run app.py
```

The Bedrock adapter uses `amazon.nova-micro-v1:0` by default. An enabled model
or inference profile can be selected with `BEDROCK_MODEL_ID`. Never commit AWS
credentials, `.env` files, `.aws/`, or Streamlit secrets.

If STS or Bedrock reports an invalid security token, refresh the temporary
workshop credentials and restart Streamlit from the same terminal.

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
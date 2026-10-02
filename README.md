# ClearLegacy

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
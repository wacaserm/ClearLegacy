"""Thin optional adapter around the documented core module contracts."""

import importlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = PROJECT_ROOT / "sample_data"
FIXTURE_LABELS = {
    "morgan": "Jordan Morgan",
    "patel": "Sam Patel",
    "rivera": "Robin Rivera",
}


class BackendUnavailableError(RuntimeError):
    """Raised when a documented backend module is not available."""


def _optional_module(name):
    try:
        return importlib.import_module(name), None
    except ModuleNotFoundError as error:
        if error.name in {"core", name}:
            return None, None
        return None, error
    except Exception as error:
        return None, error


def backend_status():
    modules = {}
    errors = {}
    for name in ("core.store", "core.document_reader", "core.pipeline"):
        module, error = _optional_module(name)
        modules[name] = module
        if error:
            errors[name] = str(error)
    return {
        "store": modules["core.store"],
        "reader": modules["core.document_reader"],
        "pipeline": modules["core.pipeline"],
        "errors": errors,
    }


def _fixture_households():
    if not SAMPLE_DATA.exists():
        return []
    households = []
    for folder in sorted(SAMPLE_DATA.iterdir()):
        if not folder.is_dir():
            continue
        parts = folder.name.split("_", maxsplit=1)
        if len(parts) != 2:
            continue
        slug = parts[1].split("_", maxsplit=1)[0].lower()
        households.append({"clientId": slug, "name": FIXTURE_LABELS.get(slug, f"{slug.title()} household")})
    return households


def _client_id(client):
    if isinstance(client, str):
        return client
    return str(client.get("clientId") or client.get("client_id") or client.get("id") or "")


def _client_name(client, client_id):
    if isinstance(client, dict):
        name = client.get("name") or client.get("clientName") or client.get("client_name")
        if name:
            return str(name)
    return FIXTURE_LABELS.get(client_id, f"{client_id.title()} household")


def get_households(backend=None):
    backend = backend or backend_status()
    store = backend["store"]
    get_clients = getattr(store, "get_clients", None) if store else None
    if callable(get_clients):
        clients = get_clients()
        if not isinstance(clients, list):
            raise ValueError("core.store.get_clients() must return a list.")
        return [
            {"clientId": _client_id(client), "name": _client_name(client, _client_id(client)), "record": client}
            for client in clients
            if _client_id(client)
        ]
    return [{**client, "record": None} for client in _fixture_households()]


def get_client(client_id, backend=None):
    backend = backend or backend_status()
    store = backend["store"]
    get_client_record = getattr(store, "get_client", None) if store else None
    if callable(get_client_record):
        record = get_client_record(client_id)
        if record is not None:
            return record
    return {"clientId": client_id, "name": FIXTURE_LABELS.get(client_id, f"{client_id.title()} household")}


def get_accounts(client_id, backend=None):
    backend = backend or backend_status()
    store = backend["store"]
    get_account_records = getattr(store, "get_accounts", None) if store else None
    if not callable(get_account_records):
        return []
    accounts = get_account_records(client_id)
    if not isinstance(accounts, list):
        raise ValueError("core.store.get_accounts(client_id) must return a list.")
    return accounts


def supported_upload_types(backend=None):
    backend = backend or backend_status()
    reader = backend["reader"]
    advertised = getattr(reader, "SUPPORTED_EXTENSIONS", None) if reader else None
    if advertised is None and reader:
        advertised = getattr(reader, "SUPPORTED_FILE_TYPES", None)
    normalized = {str(value).lower().lstrip(".") for value in advertised or []}
    file_types = ["pdf", "docx"]
    if "csv" in normalized:
        file_types.append("csv")
    # Image uploads are OCR-only, so offer them only when the reader supports them and Textract is on.
    from core import config

    if config.use_textract():
        file_types.extend(ext for ext in ("png", "jpg", "jpeg", "tif", "tiff") if ext in normalized)
    return file_types


def preview_documents(documents, backend=None):
    backend = backend or backend_status()
    reader = backend["reader"]
    read_document = getattr(reader, "read_document", None) if reader else None
    previews = []
    errors = []
    if not documents:
        return previews, errors
    if not callable(read_document):
        return previews, errors
    for document in documents:
        try:
            extracted = read_document(document["file_bytes"], document["filename"])
            if not isinstance(extracted, dict):
                raise ValueError("The document reader returned an unsupported response.")
            extracted["filename"] = document["filename"]
            extracted["category"] = document["category"]
            previews.append(extracted)
        except Exception as error:
            errors.append((document["filename"], str(error)))
    return previews, errors


def analyze_documents(client_id, documents, backend=None, previews=None):
    """Run core.pipeline.analyze once, on the raw uploads, and label sources by filename.

    The pipeline treats dict inputs as already-read documents, so uploads are
    passed as (file_bytes, filename) pairs for it to read.
    """
    backend = backend or backend_status()
    pipeline = backend["pipeline"]
    analyze = getattr(pipeline, "analyze", None) if pipeline else None
    if not callable(analyze):
        raise BackendUnavailableError(
            "Analysis is unavailable because core.pipeline.analyze(client_id, documents) is not configured."
        )
    result = analyze(client_id, [(document["file_bytes"], document["filename"]) for document in documents])
    if isinstance(result, dict):
        _label_sources(result, previews or [])
        # Session-only copy of the read text so Q&A can quote whole documents.
        result["documents"] = [
            {"sourceId": p.get("sourceId"), "filename": p.get("filename"), "docType": p.get("docType"),
             "sections": p.get("sections", [])}
            for p in previews or [] if p.get("sourceId")
        ]
    return result


def _label_sources(result, previews):
    """Add filenames to evidence and replace opaque source IDs in messages."""
    names = {
        preview.get("sourceId"): preview.get("filename")
        for preview in previews
        if preview.get("sourceId") and preview.get("filename")
    }
    if not names:
        return
    result["sourceNames"] = names
    for finding in result.get("findings", []) or []:
        for item in finding.get("evidence", []) or []:
            if isinstance(item, dict) and item.get("sourceId") in names:
                item.setdefault("filename", names[item["sourceId"]])
    for key in ("clarificationQuestions", "warnings"):
        messages = []
        for message in result.get(key, []) or []:
            text = str(message)
            for source_id, filename in names.items():
                text = text.replace(source_id, filename)
            messages.append(text)
        result[key] = messages


def summarize(client, findings):
    """Return a short AI case summary, or None. Called once after a live analysis."""
    if not findings:
        return None
    try:
        from core.explain import summarize_case

        return summarize_case(client, findings).get("summary")
    except Exception:
        return None


def _facts_from_findings(findings):
    """Validated document quotes from findings, for Q&A when the pipeline omits facts."""
    by_source = {}
    for finding in findings or []:
        for item in finding.get("evidence", []) or []:
            if isinstance(item, dict) and item.get("sourceType") == "document" and item.get("quote"):
                facts = by_source.setdefault(item.get("sourceId"), [])
                fact = {"field": "evidence", "value": item["quote"], "location": item.get("location"), "quote": item["quote"]}
                if fact not in facts:
                    facts.append(fact)
    return [{"sourceId": source_id, "docType": None, "facts": facts} for source_id, facts in by_source.items()]


def _facts_from_documents(documents):
    """Document sections as quotable text; citations must still match this text."""
    return [
        {
            "sourceId": document["sourceId"],
            "docType": document.get("docType"),
            "facts": [
                {"field": "document_text", "value": document.get("filename") or "", "location": section.get("location"),
                 "quote": section.get("text", "")}
                for section in document.get("sections", []) if section.get("text")
            ],
        }
        for document in documents or [] if document.get("sourceId")
    ]


def ask_question(question, client, accounts, analysis, history):
    """Answer an advisor question from the current analysis. Raises on Bedrock errors.

    Uses validated facts if the pipeline returns them, else the read document
    text, else the quotes inside findings.
    """
    from core.assistant import answer_question

    findings = analysis.get("findings", [])
    facts_list = (
        analysis.get("facts")
        or _facts_from_documents(analysis.get("documents"))
        or _facts_from_findings(findings)
    )
    return answer_question(question, facts_list, client, accounts, findings, history)


def persist_decision(client_id, analysis_id, finding_id, decision, reviewer, note, backend=None):
    backend = backend or backend_status()
    store = backend["store"]
    log_decision = getattr(store, "log_decision", None) if store else None
    if not callable(log_decision):
        return {"status": "Session-only", "error": None}
    try:
        result = log_decision(client_id, analysis_id, finding_id, decision, reviewer, note)
        if result is False:
            return {"status": "Session-only", "error": "The decision store did not confirm persistence."}
        return {"status": "Persistently saved", "error": None}
    except Exception as error:
        return {"status": "Session-only", "error": str(error)}


def get_audit(client_id, backend=None):
    backend = backend or backend_status()
    store = backend["store"]
    get_audit_records = getattr(store, "get_audit", None) if store else None
    if not callable(get_audit_records):
        return [], None
    try:
        records = get_audit_records(client_id)
        if not isinstance(records, list):
            raise ValueError("core.store.get_audit(client_id) must return a list.")
        return records, None
    except Exception as error:
        return [], str(error)


def sample_analysis(client_id):
    """Return clearly labeled fixture outcomes, never used as a live fallback."""
    if client_id == "morgan":
        return {
            "analysisId": "sample-morgan-fixtures",
            "status": "review_needed",
            "findings": [
                {
                    "findingId": "MORGAN-IRA-PRIMARY",
                    "priority": "high",
                    "title": "IRA primary beneficiary differs from stated intention",
                    "explanation": "The planning summary names Casey Morgan as the intended primary beneficiary, while the supplied IRA snapshot names Taylor Morgan. Confirm whether the difference is intentional.",
                    "followUpQuestion": "Does Jordan want to update the IRA designation to match the stated intention?",
                    "recommendedAction": "Confirm the current designation and the client's intention; route any requested change through the account's normal process.",
                    "evidence": [
                        {
                            "sourceType": "document",
                            "sourceId": "MORGAN-PLAN-2026-09-25",
                            "filename": "planning_summary.pdf",
                            "location": "page 1",
                            "quote": "I want Casey Morgan to receive 100% as primary beneficiary of my IRA DEMO-MORGAN-IRA.",
                        },
                        {
                            "sourceType": "account",
                            "sourceId": "MORGAN-ACCOUNT-SNAPSHOT-2026-09-28",
                            "filename": "account_records.pdf",
                            "location": "page 1",
                            "quote": "Account DEMO-MORGAN-IRA: Primary beneficiary is Taylor Morgan, former spouse, 100%.",
                        },
                    ],
                },
                {
                    "findingId": "MORGAN-IRA-CONTINGENT",
                    "priority": "review",
                    "title": "Intended contingent beneficiaries are absent from the supplied snapshot",
                    "explanation": "The planning summary names Avery Morgan and Riley Morgan as contingent beneficiaries, but the supplied IRA snapshot says no contingent beneficiaries are listed.",
                    "followUpQuestion": "Can the client provide a current IRA designation and confirm whether Avery and Riley should remain contingent beneficiaries?",
                    "recommendedAction": "Request a current beneficiary record and confirm the intended contingent allocation with the client.",
                    "evidence": [
                        {
                            "sourceType": "document",
                            "sourceId": "MORGAN-PLAN-2026-09-25",
                            "filename": "planning_summary.pdf",
                            "location": "page 1",
                            "quote": "If Casey cannot inherit, I want Avery Morgan and Riley Morgan to be contingent beneficiaries of that IRA, equally at 50% each.",
                        },
                        {
                            "sourceType": "account",
                            "sourceId": "MORGAN-ACCOUNT-SNAPSHOT-2026-09-28",
                            "filename": "account_records.pdf",
                            "location": "page 1",
                            "quote": "No contingent beneficiaries are listed in this supplied snapshot.",
                        },
                    ],
                },
            ],
            "clarificationQuestions": [],
            "warnings": [],
        }
    if client_id == "patel":
        return {
            "analysisId": "sample-patel-fixtures",
            "status": "no_discrepancies_found",
            "findings": [],
            "clarificationQuestions": [],
            "warnings": [],
        }
    if client_id == "rivera":
        return {
            "analysisId": "sample-rivera-fixtures",
            "status": "needs_information",
            "findings": [],
            "clarificationQuestions": [
                "Can the client provide a current account snapshot, especially for the brokerage account?",
                "Did the client update IRA beneficiaries during summer 2026? If so, can the completed designation be supplied?",
                "How does the client want Harper Chen to be provided for, and which account or instrument should be considered?",
            ],
            "warnings": [
                "The supplied account snapshot is dated 2025-11-01 and predates the reported possible summer 2026 update.",
                "The brokerage export contains no beneficiary data; this does not confirm that no designation exists.",
            ],
        }
    raise KeyError(f"No fixture sample is available for {client_id}.")

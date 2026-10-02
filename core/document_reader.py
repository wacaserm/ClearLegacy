"""Read selectable-text PDF and DOCX files into the shared document shape."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any


def _document_type(filename: str) -> str:
	name = Path(filename).stem.lower()
	if "planning" in name:
		return "planning_summary"
	if "account" in name or "beneficiar" in name:
		return "account_records"
	return Path(filename).suffix.lower().lstrip(".") or "unknown"


def _result(
	file_bytes: bytes,
	filename: str,
	sections: list[dict[str, str]],
	warnings: list[str],
	status: str = "ok",
) -> dict[str, Any]:
	return {
		"sourceId": f"sha256-{hashlib.sha256(file_bytes).hexdigest()[:24]}",
		"filename": Path(filename).name,
		"docType": _document_type(filename),
		"sections": sections,
		"warnings": warnings,
		"status": status,
	}


def _read_pdf(file_bytes: bytes, filename: str) -> dict[str, Any]:
	try:
		from pypdf import PdfReader
	except ImportError:
		return _result(
			file_bytes,
			filename,
			[],
			["PDF reading is unavailable because the pypdf dependency is not installed."],
			"failed",
		)

	try:
		reader = PdfReader(BytesIO(file_bytes))
		if reader.is_encrypted:
			return _result(
				file_bytes,
				filename,
				[],
				["The PDF is encrypted and could not be read without a password."],
				"failed",
			)

		sections: list[dict[str, str]] = []
		warnings: list[str] = []
		for page_number, page in enumerate(reader.pages, start=1):
			text = (page.extract_text() or "").strip()
			sections.append({"location": f"page {page_number}", "text": text})
			if not text:
				warnings.append(f"Page {page_number} requires OCR; no selectable text was extracted.")

		if not sections:
			warnings.append("The PDF contains no pages.")
		status = "needs_ocr" if any("requires OCR" in warning for warning in warnings) else "ok"
		if not any(section["text"] for section in sections) and sections:
			status = "needs_ocr"
		return _result(file_bytes, filename, sections, warnings, status)
	except Exception as exc:
		return _result(file_bytes, filename, [], [f"The PDF could not be read: {exc.__class__.__name__}."], "failed")


def _read_docx(file_bytes: bytes, filename: str) -> dict[str, Any]:
	try:
		from docx import Document
		from docx.document import Document as DocumentType
		from docx.table import Table, _Cell
		from docx.text.paragraph import Paragraph
	except ImportError:
		return _result(
			file_bytes,
			filename,
			[],
			["DOCX reading is unavailable because the python-docx dependency is not installed."],
			"failed",
		)

	try:
		document = Document(BytesIO(file_bytes))
		sections: list[dict[str, str]] = []
		paragraph_number = 0
		table_number = 0
		for block in _iter_block_items(document, DocumentType, _Cell, Paragraph, Table):
			if isinstance(block, Paragraph):
				paragraph_number += 1
				text = block.text.strip()
				if text:
					sections.append({"location": f"paragraph {paragraph_number}", "text": text})
			else:
				table_number += 1
				for row_number, row in enumerate(block.rows, start=1):
					text = " | ".join(cell.text.strip() for cell in row.cells).strip()
					if text:
						sections.append(
							{"location": f"table {table_number} row {row_number}", "text": text}
						)

		warnings = [] if sections else ["The DOCX contains no readable paragraphs or table rows."]
		return _result(file_bytes, filename, sections, warnings, "ok" if sections else "empty")
	except Exception as exc:
		return _result(file_bytes, filename, [], [f"The DOCX could not be read: {exc.__class__.__name__}."], "failed")


def _iter_block_items(document: Any, document_type: Any, cell_type: Any, paragraph_type: Any, table_type: Any):
	parent = document.element.body if isinstance(document, document_type) else document._tc
	for child in parent.iterchildren():
		if child.tag.endswith("}p"):
			yield paragraph_type(child, parent)
		elif child.tag.endswith("}tbl"):
			yield table_type(child, parent)


def read_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
	"""Read one upload and return source-located text without performing OCR."""
	if not isinstance(file_bytes, (bytes, bytearray)):
		return {
			"sourceId": "",
			"filename": Path(str(filename)).name,
			"docType": _document_type(str(filename)),
			"sections": [],
			"warnings": ["The document content must be bytes."],
			"status": "failed",
		}

	content = bytes(file_bytes)
	safe_filename = Path(str(filename)).name
	if not content:
		return _result(content, safe_filename, [], ["The uploaded file is empty."], "empty")

	extension = Path(safe_filename).suffix.lower()
	if extension == ".pdf":
		return _read_pdf(content, safe_filename)
	if extension == ".docx":
		return _read_docx(content, safe_filename)
	return _result(content, safe_filename, [], [f"Unsupported document type: {extension or 'unknown'}.",], "unsupported")

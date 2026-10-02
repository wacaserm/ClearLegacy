"""Read PDF, DOCX, and (with Textract) image files into the shared document shape.

Pages with no text layer are OCR'd with Amazon Textract when
CLEARLEGACY_USE_TEXTRACT=1 (the default). On any OCR error the page stays empty
with a warning, which is the previous behavior.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SUPPORTED_EXTENSIONS = [".pdf", ".docx", *sorted(IMAGE_EXTENSIONS)]


def _document_type(filename: str) -> str:
	name = Path(filename).stem.lower()
	if "planning" in name:
		return "planning_summary"
	if "account" in name or "beneficiar" in name:
		return "account_records"
	if "trust" in name:
		return "trust"
	if "poa" in name or "power_of_attorney" in name or "power-of-attorney" in name:
		return "poa"
	if "will" in name:
		return "will"
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
		ocr_pages = _ocr_empty_pages(file_bytes, filename, sections, warnings)
		status = "needs_ocr" if any("requires OCR" in warning for warning in warnings) else "ok"
		if not any(section["text"] for section in sections) and sections:
			status = "needs_ocr"
		result = _result(file_bytes, filename, sections, warnings, status)
		if ocr_pages:
			result["ocrPages"] = ocr_pages
		return result
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


def _ocr_empty_pages(file_bytes: bytes, filename: str, sections: list[dict[str, str]], warnings: list[str]) -> list[int]:
	"""Fill pages with no text layer using Textract; leave them empty on any error.

	Returns the page numbers read with OCR (informational, not a warning).
	"""
	ocr_pages: list[int] = []
	empty = [index for index, section in enumerate(sections) if not section["text"]]
	if not empty:
		return ocr_pages
	from core import config

	if not config.use_textract():
		return ocr_pages
	from core.ocr import OcrError, ocr_multipage, ocr_single

	try:
		if len(sections) == 1:
			texts = {1: ocr_single(file_bytes)}
		else:
			texts = ocr_multipage(file_bytes, Path(filename).name)
	except OcrError as exc:
		message = f"OCR unavailable for {Path(filename).name}; scanned pages were left empty ({exc})."
		warnings.append(message)
		config.aws_warning(message)
		return ocr_pages
	for index in empty:
		page_number = index + 1
		text = (texts.get(page_number) or "").strip()
		if text:
			sections[index]["text"] = text
			warnings[:] = [w for w in warnings if not w.startswith(f"Page {page_number} requires OCR")]
			ocr_pages.append(page_number)
	return ocr_pages


def _read_image(file_bytes: bytes, filename: str) -> dict[str, Any]:
	from core import config

	if not config.use_textract():
		return _result(file_bytes, filename, [], ["Image uploads need Textract (CLEARLEGACY_USE_TEXTRACT=1)."], "needs_ocr")
	sections = [{"location": "page 1", "text": ""}]
	warnings = ["Page 1 requires OCR; no selectable text was extracted."]
	ocr_pages = _ocr_empty_pages(file_bytes, filename, sections, warnings)
	status = "needs_ocr" if not sections[0]["text"] else "ok"
	result = _result(file_bytes, filename, sections, warnings, status)
	if ocr_pages:
		result["ocrPages"] = ocr_pages
	return result


def read_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
	"""Read one upload and return source-located text (OCR only for pages with no text layer)."""
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
	if extension in IMAGE_EXTENSIONS:
		return _read_image(content, safe_filename)
	return _result(content, safe_filename, [], [f"Unsupported document type: {extension or 'unknown'}.",], "unsupported")

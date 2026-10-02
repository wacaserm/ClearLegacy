"""Render the Johnson .txt fixtures into real PDFs (one PDF page per === PAGE N === block).

Usage: python scripts/make_fixture_pdfs.py
"""

import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.extract import read_txt  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SOURCES = ["johnson_will.txt", "johnson_trust.txt", "johnson_poa.txt"]


def render(txt_path: Path, pdf_path: Path) -> None:
    style = getSampleStyleSheet()["BodyText"]
    story = []
    pages = read_txt(txt_path)
    for i, page in enumerate(pages):
        for para in re.split(r"\n\s*\n", page["text"].strip()):
            story.append(Paragraph(escape(para).replace("\n", "<br/>"), style))
            story.append(Spacer(1, 6))
        if i < len(pages) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(pdf_path), pagesize=LETTER, title=txt_path.stem).build(story)


if __name__ == "__main__":
    out_dir = FIXTURES / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        out = out_dir / name.replace(".txt", ".pdf")
        render(FIXTURES / name, out)
        print(f"wrote {out.relative_to(ROOT)}")

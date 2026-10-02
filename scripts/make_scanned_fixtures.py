"""Render sample PDFs to image-only PDFs (no text layer), to test Textract OCR.

Usage: python scripts/make_scanned_fixtures.py
Dev-only dependency: pip install pypdfium2 (not needed to run the app).
"""

from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "scanned"
SOURCES = {
    "morgan_planning_summary_scanned.pdf": ROOT / "sample_data" / "01_morgan_discrepancies" / "planning_summary.pdf",
    "johnson_will_scanned_2page.pdf": ROOT / "tests" / "fixtures" / "pdf" / "johnson_will.pdf",
}


def render(source: Path, target: Path, scale: float = 200 / 72) -> None:
    pdf = pdfium.PdfDocument(str(source))
    images = [page.render(scale=scale).to_pil().convert("RGB") for page in pdf]
    images[0].save(target, "PDF", resolution=200, save_all=True, append_images=images[1:])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, source in SOURCES.items():
        render(source, OUT / name)
        print(f"wrote {(OUT / name).relative_to(ROOT)}")

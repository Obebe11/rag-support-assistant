# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "reportlab>=4.2,<5",  # BSD-3-Clause
#     "pypdf>=5,<7",        # BSD-3-Clause
# ]
# ///
"""Build the PDF documents of the Northline corpus from their Markdown sources.

Usage (from the repository root):

    uv run knowledge-base/northline/pdf-source/build_pdfs.py          # rebuild
    uv run knowledge-base/northline/pdf-source/build_pdfs.py --check  # verify only

The script reads ``manifest.json`` and processes every document that has
``"format": "pdf"``. The ``source_path`` field points to the Markdown source
and ``path`` to the PDF output.

Each source uses a small Markdown subset: ``#``/``##``/``###`` headings,
paragraphs, ``-`` bullet lists, ``1.`` numbered lists, pipe tables,
``**bold**`` and a ``<!-- pagebreak -->`` line that starts a new PDF page.
Evaluation cases cite PDF page numbers, so every source page must fit on
exactly one PDF page; the build fails if a page overflows.

After building (or with ``--check``), the script extracts the text layer of
each PDF and confirms that every block of a source page appears on the same
PDF page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CORPUS_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
PAGE_BREAK = "<!-- pagebreak -->"
PUBLISHER = "Northline Office Equipment"

BODY = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=10, leading=13.5, alignment=TA_LEFT
)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=9.5, leading=12)
CELL_HEAD = ParagraphStyle("CellHead", parent=CELL, fontName="Helvetica-Bold")
HEADINGS = {
    1: ParagraphStyle(
        "H1", parent=BODY, fontName="Helvetica-Bold", fontSize=18, leading=22
    ),
    2: ParagraphStyle(
        "H2", parent=BODY, fontName="Helvetica-Bold", fontSize=13, leading=16
    ),
    3: ParagraphStyle(
        "H3", parent=BODY, fontName="Helvetica-Bold", fontSize=11, leading=14
    ),
}
SPACE_BEFORE = {1: 0, 2: 10, 3: 7}
SPACE_AFTER = {1: 8, 2: 5, 3: 4}

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
BULLET_RE = re.compile(r"^-\s+(.*)$")
NUMBERED_RE = re.compile(r"^\d+\.\s+(.*)$")
TABLE_DIVIDER_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")


def parse_page(text: str) -> list[tuple]:
    """Turn one source page into a list of blocks.

    Block shapes: ("heading", level, text), ("paragraph", text),
    ("bullets", [text]), ("numbered", [text]), ("table", [[cell]]).
    """
    blocks: list[tuple] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            blocks.append(("heading", len(heading.group(1)), heading.group(2).strip()))
            index += 1
            continue
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if not TABLE_DIVIDER_RE.match(row):
                    rows.append([cell.strip() for cell in row.strip("|").split("|")])
                index += 1
            blocks.append(("table", rows))
            continue
        for kind, pattern in (("bullets", BULLET_RE), ("numbered", NUMBERED_RE)):
            if pattern.match(line):
                items = []
                while index < len(lines):
                    match = pattern.match(lines[index].strip())
                    if not match:
                        break
                    items.append(match.group(1).strip())
                    index += 1
                blocks.append((kind, items))
                break
        else:
            paragraph = []
            while index < len(lines):
                current = lines[index].strip()
                if (
                    not current
                    or current.startswith("|")
                    or HEADING_RE.match(current)
                    or BULLET_RE.match(current)
                    or NUMBERED_RE.match(current)
                ):
                    break
                paragraph.append(current)
                index += 1
            blocks.append(("paragraph", " ".join(paragraph)))
    return blocks


def read_pages(source: Path) -> list[list[tuple]]:
    pages = source.read_text(encoding="utf-8").split(PAGE_BREAK)
    return [parse_page(page) for page in pages]


def markup(text: str) -> str:
    """Convert inline Markdown to the reportlab paragraph markup."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def plain(text: str) -> str:
    return text.replace("**", "")


def block_texts(block: tuple) -> list[str]:
    """Plain-text fragments of a block, used to verify the PDF text layer."""
    kind = block[0]
    if kind == "heading":
        return [plain(block[2])]
    if kind == "paragraph":
        return [plain(block[1])]
    if kind in ("bullets", "numbered"):
        return [plain(item) for item in block[1]]
    return [plain(cell) for row in block[1] for cell in row if cell]


def table_flowable(rows: list[list[str]], width: float) -> Table:
    column_count = len(rows[0])
    longest = [
        max(len(plain(row[column])) for row in rows) for column in range(column_count)
    ]
    weights = [min(max(length, 10), 60) for length in longest]
    column_widths = [width * weight / sum(weights) for weight in weights]
    data = [
        [
            Paragraph(markup(cell), CELL_HEAD if row_index == 0 else CELL)
            for cell in row
        ]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=column_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9aa3ad")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def page_flowables(blocks: list[tuple], width: float) -> list:
    flowables: list = []
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            level, text = block[1], block[2]
            flowables.append(Spacer(1, SPACE_BEFORE[level]))
            flowables.append(Paragraph(markup(text), HEADINGS[level]))
            flowables.append(Spacer(1, SPACE_AFTER[level]))
        elif kind == "paragraph":
            flowables.append(Paragraph(markup(block[1]), BODY))
            flowables.append(Spacer(1, 6))
        elif kind in ("bullets", "numbered"):
            items = [
                ListItem(Paragraph(markup(item), BODY), spaceAfter=2)
                for item in block[1]
            ]
            options = (
                {"bulletType": "bullet", "start": "-"}
                if kind == "bullets"
                else {"bulletType": "1", "bulletFormat": "%s."}
            )
            flowables.append(
                ListFlowable(items, leftIndent=16, bulletFontSize=10, **options)
            )
            flowables.append(Spacer(1, 6))
        else:
            flowables.append(table_flowable(block[1], width))
            flowables.append(Spacer(1, 8))
    return flowables


def build_pdf(entry: dict, pages: list[list[tuple]], output: Path) -> None:
    total = len(pages)
    footer = f"{PUBLISHER}  |  {entry['title']}  |  Version {entry['version']}"

    def draw_footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5b6570"))
        canvas.drawString(document.leftMargin, 0.5 * inch, footer)
        canvas.drawRightString(
            letter[0] - document.rightMargin,
            0.5 * inch,
            f"Page {canvas.getPageNumber()} of {total}",
        )
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.9 * inch,
        title=entry["title"],
        author=f"{PUBLISHER} (fictional company)",
        subject=f"Version {entry['version']}, effective {entry['effective_date']}",
        invariant=1,  # fixed timestamps and IDs: rebuilding gives identical bytes
    )
    story: list = []
    for number, blocks in enumerate(pages, start=1):
        story.extend(page_flowables(blocks, document.width))
        if number < total:
            story.append(PageBreak())
    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)


def squash(text: str) -> str:
    """Drop all whitespace so that line wrapping does not affect comparison."""
    return re.sub(r"\s+", "", text)


def check_pdf(entry: dict, pages: list[list[tuple]], output: Path) -> list[str]:
    problems: list[str] = []
    if not output.exists():
        return [f"{entry['doc_id']}: {output.name} does not exist; run the build"]
    reader = PdfReader(str(output))
    if len(reader.pages) != len(pages):
        return [
            f"{entry['doc_id']}: PDF has {len(reader.pages)} pages, "
            f"source has {len(pages)}. A source page overflows; shorten it "
            f"or move the page break."
        ]
    if entry.get("page_count") != len(pages):
        problems.append(
            f"{entry['doc_id']}: manifest page_count is {entry.get('page_count')}, "
            f"expected {len(pages)}"
        )
    for number, (pdf_page, blocks) in enumerate(zip(reader.pages, pages), start=1):
        extracted = squash(pdf_page.extract_text())
        if not extracted:
            problems.append(f"{entry['doc_id']}: page {number} has no text layer")
            continue
        for block in blocks:
            for fragment in block_texts(block):
                if squash(fragment) not in extracted:
                    problems.append(
                        f"{entry['doc_id']}: page {number} text layer is missing "
                        f"{fragment[:70]!r}"
                    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the existing PDFs against their sources without rebuilding",
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = [doc for doc in manifest["documents"] if doc["format"] == "pdf"]
    problems: list[str] = []
    for entry in entries:
        source = CORPUS_DIR / entry["source_path"]
        output = CORPUS_DIR / entry["path"]
        pages = read_pages(source)
        if not args.check:
            build_pdf(entry, pages, output)
        entry_problems = check_pdf(entry, pages, output)
        problems.extend(entry_problems)
        status = "FAILED" if entry_problems else "ok"
        action = "checked" if args.check else "built"
        print(f"{action} {entry['path']}: {len(pages)} pages, text layer {status}")

    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

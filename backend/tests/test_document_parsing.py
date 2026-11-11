"""Parsing and chunking: Markdown headings, PDF pages, tables, limits."""

import time

import pytest

from app.services.documents.chunking import build_chunks, embedding_text
from app.services.documents.parsing import (
    DocumentFormat,
    DocumentParseError,
    ParsedDocument,
    Section,
    _PdfPage,
    _running_lines,
    detect_format,
    find_title,
    parse_markdown,
    parse_pdf,
)
from tests.kb import EVAL_FIXTURES, NORTHLINE_DOCUMENTS, blank_pdf

MARKDOWN = b"""# Returns Policy

Version 2.0.

## Return window

You can return most items within 30 days.

## Refunds

### Timing

Refunds are issued within 7 business days.

```
# not a heading
```

## Fees

| Condition | Refund |
| --- | --- |
| Unopened | 100% |
| Opened | Price less a 15% restocking fee |
"""


def _sections(document: ParsedDocument) -> dict[tuple[str, ...], Section]:
    return {section.heading_path: section for section in document.sections}


def test_markdown_sections_keep_the_heading_path_without_the_document_title() -> None:
    document = parse_markdown(MARKDOWN)
    sections = _sections(document)

    assert document.title == "Returns Policy"
    assert document.page_count is None
    assert list(sections) == [(), ("Return window",), ("Refunds", "Timing"), ("Fees",)]
    assert sections[()].blocks == ("Version 2.0.",)
    assert sections[("Return window",)].blocks == ("You can return most items within 30 days.",)
    assert all(section.page_number is None for section in document.sections)


def test_markdown_code_fences_are_text_not_headings() -> None:
    timing = _sections(parse_markdown(MARKDOWN))[("Refunds", "Timing")]

    assert timing.blocks[1] == "```\n# not a heading\n```"


def test_markdown_heading_path_of_a_nested_faq_entry_ends_with_the_exact_heading() -> None:
    document = parse_markdown((NORTHLINE_DOCUMENTS / "faq.md").read_bytes())

    assert document.title == "Frequently Asked Questions"
    assert ("Returns", "How long do I have to return an item?") in _sections(document)


def test_markdown_html_comments_are_not_indexed() -> None:
    document = parse_markdown((EVAL_FIXTURES / "lp420-setup-notes.md").read_bytes())
    text = "\n".join(block for section in document.sections for block in section.blocks)

    assert "Drivers are available for Windows 10" in text
    assert "Linux" not in text
    assert "password" not in text


def test_markdown_that_is_not_utf8_or_has_no_text_is_rejected() -> None:
    with pytest.raises(DocumentParseError, match="UTF-8"):
        parse_markdown(b"\xff\xfe\x00broken")
    with pytest.raises(DocumentParseError, match="no text"):
        parse_markdown(b"# Only a title\n\n<!-- hidden -->\n")


def test_pdf_sections_keep_page_numbers_and_headings() -> None:
    document = parse_pdf((NORTHLINE_DOCUMENTS / "warranty-policy.pdf").read_bytes())
    pages = {section.heading_path: section.page_number for section in document.sections}

    assert document.title == "Warranty Policy"
    assert document.page_count == 3
    assert pages[("Warranty periods",)] == 1
    assert pages[("Third-party supplies",)] == 2
    assert pages[("Advance replacement",)] == 3
    assert {section.page_number for section in document.sections} == {1, 2, 3}


def test_pdf_running_headers_and_page_numbers_are_dropped() -> None:
    document = parse_pdf((NORTHLINE_DOCUMENTS / "warranty-policy.pdf").read_bytes())
    text = "\n".join(block for section in document.sections for block in section.blocks)

    assert "Page 1 of 3" not in text
    assert "Northline Office Equipment  |" not in text


def test_pdf_table_rows_stay_on_one_line_and_wrapped_lines_are_joined() -> None:
    sections = _sections(parse_pdf((NORTHLINE_DOCUMENTS / "warranty-policy.pdf").read_bytes()))
    periods = "\n".join(sections[("Warranty periods",)].blocks)
    supplies = "\n".join(sections[("Third-party supplies",)].blocks)

    assert "Product | Warranty period" in periods
    assert "L-125 Thermal Laminator | 1 year" in periods
    assert (
        "Using third-party toner, labels or laminating pouches does not by itself void the "
        "warranty." in supplies
    )


def test_pdf_nested_headings_and_wrapped_table_cells() -> None:
    document = parse_pdf((NORTHLINE_DOCUMENTS / "service-and-maintenance-guide.pdf").read_bytes())
    sections = _sections(document)
    c360 = sections[("Printer maintenance", "C-360 Color Multifunction Printer")]

    assert c360.page_number == 2
    assert (
        "Replace the maintenance kit NL-MK360 (fuser, transfer roller and feed rollers), "
        "$289.00 | Every 150,000 pages" in c360.blocks[0]
    )
    assert (
        sections[("Shredder maintenance", "S-300 Cross-Cut Shredder")]
        .blocks[0]
        .startswith("- Oil the cutting head")
    )


def test_pdf_without_a_text_layer_or_broken_is_rejected() -> None:
    with pytest.raises(DocumentParseError, match="no text layer"):
        parse_pdf(blank_pdf())
    with pytest.raises(DocumentParseError, match="not a readable PDF"):
        parse_pdf(b"%PDF-1.7\nthis is not a pdf at all")


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "expected"),
    [
        ("policy.md", "text/markdown", b"# Title", DocumentFormat.MARKDOWN),
        ("POLICY.MARKDOWN", "application/octet-stream", b"# Title", DocumentFormat.MARKDOWN),
        ("policy", "text/markdown; charset=utf-8", b"# Title", DocumentFormat.MARKDOWN),
        ("policy.pdf", "application/pdf", b"%PDF-1.7 ...", DocumentFormat.PDF),
        ("mislabeled.md", "text/markdown", b"%PDF-1.7 ...", DocumentFormat.PDF),
        ("notes.txt", "text/plain", b"plain", None),
        ("policy.pdf", "application/pdf", b"not a pdf", None),
        ("archive.docx", "application/zip", b"PK\x03\x04", None),
    ],
)
def test_format_is_detected_from_content_then_name(
    filename: str, content_type: str, data: bytes, expected: DocumentFormat | None
) -> None:
    assert detect_format(filename, content_type, data) is expected


def test_title_is_found_in_the_file() -> None:
    pdf = (NORTHLINE_DOCUMENTS / "product-c360-color-mfp.pdf").read_bytes()

    assert find_title(DocumentFormat.MARKDOWN, MARKDOWN) == "Returns Policy"
    assert find_title(DocumentFormat.MARKDOWN, b"## Section first\n\nText.\n") is None
    assert find_title(DocumentFormat.PDF, pdf) == "Northline C-360 Color Multifunction Printer"


def test_chunks_carry_heading_page_and_text() -> None:
    chunks = build_chunks(parse_markdown(MARKDOWN))

    assert [(chunk.heading, chunk.page_number) for chunk in chunks] == [
        (None, None),
        ("Return window", None),
        ("Refunds > Timing", None),
        ("Fees", None),
    ]
    assert chunks[1].content == "You can return most items within 30 days."
    assert embedding_text("Returns Policy", chunks[2]).startswith(
        "Returns Policy\nRefunds > Timing\n\nRefunds are issued"
    )


def test_a_long_section_is_split_and_a_table_header_is_repeated() -> None:
    rows = "\n".join(f"| Item {number} | {'value ' * 12}|" for number in range(40))
    document = parse_markdown(
        f"# Catalog\n\n## Prices\n\n| Item | Value |\n| --- | --- |\n{rows}\n".encode()
    )

    chunks = build_chunks(document, max_chars=600)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 600 for chunk in chunks)
    assert all(chunk.heading == "Prices" for chunk in chunks)
    assert all(chunk.content.startswith("| Item | Value |\n| --- | --- |\n") for chunk in chunks)
    assert sum(chunk.content.count("| Item ") for chunk in chunks) == 40 + len(chunks)


def test_a_long_paragraph_is_split_between_sentences() -> None:
    paragraph = " ".join(f"Sentence number {number} ends here." for number in range(60))
    document = parse_markdown(f"# Notes\n\n{paragraph}\n".encode())

    chunks = build_chunks(document, max_chars=300)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 300 for chunk in chunks)
    assert all(chunk.content.endswith("ends here.") for chunk in chunks)
    assert " ".join(chunk.content for chunk in chunks) == paragraph


def test_a_code_fence_closes_only_with_a_fence_of_its_kind() -> None:
    document = parse_markdown(
        b"# Guide\n\n## Example\n\n````\n```\n# a comment in code\n````\n\n"
        b"## Script\n\n```sh title\n# another comment\n```\n\nAfter the code.\n"
    )

    sections = _sections(document)
    assert set(sections) == {("Example",), ("Script",)}
    assert sections[("Example",)].blocks == ("````\n```\n# a comment in code\n````",)
    assert sections[("Script",)].blocks == (
        "```sh title\n# another comment\n```",
        "After the code.",
    )


def test_a_sentence_repeated_in_the_body_of_every_pdf_page_is_text() -> None:
    def page(number: int, topic: str) -> _PdfPage:
        lines = [
            "Northline Price List",
            "",
            f"{topic} products",
            *(f"{topic} item {index} costs more." for index in range(6)),
            "All prices exclude sales tax.",
            *(f"{topic} accessory {index} is optional." for index in range(6)),
            "",
            f"Page {number} of 3",
        ]
        return _PdfPage(lines=lines, fragments=[])

    running = _running_lines([page(1, "Printer"), page(2, "Shredder"), page(3, "Laminator")])

    assert running == {"Northline Price List", "Page # of #"}


def test_a_split_table_with_a_long_row_stays_within_the_limit() -> None:
    # A row that fits the limit alone, but not under the repeated header.
    row = f"| {'x' * 580} | y |"
    table = "\n".join(["| Column A | Column B |", "| --- | --- |", row, row, row])
    document = parse_markdown(f"# Catalog\n\n{table}\n".encode())

    chunks = build_chunks(document, max_chars=600)

    assert len(row) <= 600
    assert all(len(chunk.content) <= 600 for chunk in chunks)
    assert all(chunk.content.startswith("| Column A | Column B |\n| --- |") for chunk in chunks)
    assert sum(chunk.content.count("x") for chunk in chunks) == 3 * 580


def test_a_long_line_of_spaces_after_a_table_header_is_handled_quickly() -> None:
    # Was quadratic in the number of spaces when the divider was matched by one pattern.
    block = "| A | B |\n| --- |" + " " * 200_000 + "x\n| 1 | 2 |"
    document = parse_markdown(f"# Notes\n\n{block}\n".encode())

    started = time.perf_counter()
    chunks = build_chunks(document)

    assert time.perf_counter() - started < 2
    assert chunks

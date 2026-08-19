"""Tests for .docx → sections.

Every fixture here is a real .docx built in memory with python-docx, not a
hand-written JSON stand-in. The parser is the riskiest non-agent code in the
build: everything downstream addresses sections by the ids it hands out.
"""

from io import BytesIO

import pytest
from docx import Document

from app.parsing import UnparseableDocument, parse_docx


def make_docx(blocks: list[tuple[str, str]]) -> bytes:
    """Build a real .docx from (style, text) pairs."""
    document = Document()
    for style, text in blocks:
        document.add_paragraph(text, style=style)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_splits_document_into_sections_at_headings():
    data = make_docx(
        [
            ("Heading 1", "1. Executive Summary"),
            ("Normal", "Meridian has asked us to review its data landscape."),
            ("Heading 1", "2. Scope of Work"),
            ("Normal", "Our work will cover customer-facing data systems."),
        ]
    )

    parsed = parse_docx(data)

    assert [s.heading for s in parsed.sections] == [
        "1. Executive Summary",
        "2. Scope of Work",
    ]
    assert parsed.headings_detected is True


def test_section_body_holds_the_paragraphs_beneath_its_heading():
    data = make_docx(
        [
            ("Heading 1", "1. Executive Summary"),
            ("Normal", "First paragraph."),
            ("Normal", "Second paragraph."),
            ("Heading 1", "2. Scope of Work"),
            ("Normal", "Belongs to scope."),
        ]
    )

    parsed = parse_docx(data)

    assert parsed.sections[0].text == "First paragraph.\n\nSecond paragraph."
    assert parsed.sections[1].text == "Belongs to scope."


def test_sections_get_stable_sequential_ids():
    data = make_docx(
        [
            ("Heading 1", "One"),
            ("Normal", "a"),
            ("Heading 1", "Two"),
            ("Normal", "b"),
            ("Heading 1", "Three"),
            ("Normal", "c"),
        ]
    )

    ids = [s.id for s in parse_docx(data).sections]

    assert ids == ["s1", "s2", "s3"]


def test_text_before_the_first_heading_gets_a_fixed_id_not_a_shifted_one():
    """A proposal often opens with a title block or a paragraph of preamble.
    Dropping it would silently hide part of the document from the agent, and
    giving it `s1` would shift every real section's number by one."""
    data = make_docx(
        [
            ("Normal", "Prepared for Meridian Retail BV, 13 August 2026."),
            ("Heading 1", "1. Executive Summary"),
            ("Normal", "Body."),
        ]
    )

    parsed = parse_docx(data)

    assert "Prepared for Meridian Retail BV" in parsed.sections[0].text
    assert parsed.sections[0].id == "preamble"
    assert parsed.sections[1].id == "s1"
    assert len(parsed.sections) == 2


def test_falls_back_to_block_splitting_when_the_document_has_no_headings():
    data = make_docx(
        [
            ("Normal", "Scope of work"),
            ("Normal", "We will review the data flows."),
            ("Normal", ""),
            ("Normal", "Pricing"),
            ("Normal", "A fixed fee of EUR 48,000."),
        ]
    )

    parsed = parse_docx(data)

    assert parsed.headings_detected is False
    assert len(parsed.sections) == 2


def test_document_with_no_text_is_rejected():
    with pytest.raises(UnparseableDocument):
        parse_docx(make_docx([("Normal", "")]))


def test_bytes_that_are_not_a_docx_are_rejected():
    with pytest.raises(UnparseableDocument):
        parse_docx(b"this is not a docx file")

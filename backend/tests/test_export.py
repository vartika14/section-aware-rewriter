"""Tests for turning sections back into a .docx file.

Instead of checking the internal details of how python-docx builds a file, we
build a file and then read it right back in with our own reader
(parse_docx). If what comes out matches what went in, we know it worked.
"""

from app.export import build_docx
from app.parsing import Section, parse_docx


def test_a_single_section_comes_back_the_same():
    sections = [Section(id="s1", heading="1. Scope", text="The engagement is advisory.")]

    reread = parse_docx(build_docx(sections))

    assert [s.heading for s in reread.sections] == ["1. Scope"]
    assert reread.sections[0].text == "The engagement is advisory."


def test_several_sections_stay_in_the_same_order():
    sections = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000."),
    ]

    reread = parse_docx(build_docx(sections))

    assert [s.heading for s in reread.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]
    assert [s.text for s in reread.sections] == [s.text for s in sections]


def test_a_section_with_more_than_one_paragraph_comes_back_the_same():
    sections = [Section(id="s1", heading="1. Scope", text="First paragraph.\n\nSecond paragraph.")]

    reread = parse_docx(build_docx(sections))

    assert reread.sections[0].text == "First paragraph.\n\nSecond paragraph."


def test_the_opening_text_before_any_heading_comes_back_correctly():
    sections = [
        Section(id="preamble", heading="(untitled opening)", text="Proposal: Example."),
        Section(id="s1", heading="1. Scope", text="The engagement is advisory."),
    ]

    reread = parse_docx(build_docx(sections))

    assert reread.sections[0].id == "preamble"
    assert "Proposal: Example." in reread.sections[0].text
    assert reread.sections[1].heading == "1. Scope"

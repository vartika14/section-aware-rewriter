"""Tests for DRAFT: the context assembly and the rewrite call itself.

The model call is substituted at `app.rewrite.structured_completion`. Whether the
instruction is applicable to the section is decided HERE, before a conflict
check is ever run — a nonsensical instruction should never cost a DETECT call.
"""

import pytest

from app.parsing import Section
from app.rewrite import DraftResult, draft_section, find_section, render_document

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="Act on it this quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000."),
]


def test_rendered_context_includes_every_section():
    rendered = render_document(SECTIONS, focus_id="s2")
    for section in SECTIONS:
        assert section.heading in rendered
        assert section.text in rendered


def test_rendered_context_marks_the_section_being_rewritten():
    rendered = render_document(SECTIONS, focus_id="s2")
    focus_line = next(l for l in rendered.splitlines() if "2. Scope of Work" in l)
    other_line = next(l for l in rendered.splitlines() if "3. Fees" in l)
    assert "REWRITE" in focus_line
    assert "REWRITE" not in other_line


def test_draft_section_returns_the_models_new_text(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        return schema(applicable=True, new_text="Named deliverables: a map.")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    result = draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert isinstance(result, DraftResult)
    assert result.applicable is True
    assert result.new_text == "Named deliverables: a map."


def test_draft_section_sends_the_whole_document(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["user"] = user
        return schema(applicable=True, new_text="...")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert "EUR 48,000" in captured["user"]
    assert "Act on it this quarter." in captured["user"]
    assert "Be concrete." in captured["user"]


def test_draft_section_is_pinned_to_temperature_zero(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["temperature"] = kwargs.get("temperature")
        return schema(applicable=True, new_text="...")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert captured["temperature"] == 0


def test_draft_section_rejects_an_unknown_section_id():
    with pytest.raises(KeyError):
        draft_section(sections=SECTIONS, section_id="nope", instruction="Be concrete.")


def test_an_inapplicable_instruction_carries_no_new_text(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        return schema(
            applicable=False,
            inapplicable_reason="This section sets no dates to bring forward.",
            new_text=None,
        )

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    result = draft_section(sections=SECTIONS, section_id="s2", instruction="Bring the date forward.")

    assert result.applicable is False
    assert result.new_text is None
    assert "dates" in result.inapplicable_reason


def test_a_constraint_reaches_the_model(monkeypatch):
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(applicable=True, new_text="trimmed")

    monkeypatch.setattr("app.rewrite.structured_completion", capture)

    draft_section(
        sections=SECTIONS, section_id="s2", instruction="Make this concrete.",
        constraints=["3. Fees must stand exactly as written."],
    )

    assert "3. Fees must stand exactly as written." in seen["user"]


def test_no_constraints_leaves_the_prompt_as_it_was(monkeypatch):
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(applicable=True, new_text="drafted")

    monkeypatch.setattr("app.rewrite.structured_completion", capture)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Make this concrete.")

    assert "must hold" not in seen["user"]

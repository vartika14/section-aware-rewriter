"""Tests for the agent's context assembly and drafting step.

The model call itself is substituted. `app.llm.structured_completion` is the one
seam every model call passes through, which is precisely so these tests can
exercise real orchestration code without a network round trip.
"""

import pytest

from app.agent import Draft, draft_rewrite, render_document
from app.parsing import Section

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

    focus_line = next(
        line for line in rendered.splitlines() if "2. Scope of Work" in line
    )
    other_line = next(line for line in rendered.splitlines() if "3. Fees" in line)

    assert "REWRITE" in focus_line
    assert "REWRITE" not in other_line


def test_draft_rewrite_returns_the_models_new_text(monkeypatch):
    captured = {}

    def fake_completion(*, system, user, schema):
        captured["system"] = system
        captured["user"] = user
        return schema(new_text="Named deliverables: a current-state map.")

    monkeypatch.setattr("app.agent.structured_completion", fake_completion)

    result = draft_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Make this concrete. Name the deliverables.",
    )

    assert isinstance(result, Draft)
    assert result.new_text == "Named deliverables: a current-state map."


def test_draft_rewrite_sends_the_whole_document_not_just_the_section(monkeypatch):
    """The rewrite must be informed by the rest of the document. If the fee in
    s3 never reaches the model, nothing downstream can be consistent with it."""
    captured = {}

    def fake_completion(*, system, user, schema):
        captured["user"] = user
        return schema(new_text="...")

    monkeypatch.setattr("app.agent.structured_completion", fake_completion)

    draft_rewrite(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert "EUR 48,000" in captured["user"]
    assert "Act on it this quarter." in captured["user"]
    assert "Be concrete." in captured["user"]


def test_draft_rewrite_rejects_an_unknown_section_id():
    with pytest.raises(KeyError):
        draft_rewrite(sections=SECTIONS, section_id="nope", instruction="Be concrete.")

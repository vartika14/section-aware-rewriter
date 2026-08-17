"""Tests for DETECT and the interrupt policy — conflicts.py in full.

Split into three parts as the file grows across two tasks: DETECT (this part,
the one LLM call, tested with the seam substituted), ground() and decide() (pure
Python, hand-built findings including dishonest ones — this is the new interrupt
policy's test suite, the direct replacement for the old test_policy.py).
"""

import pytest

from app.parsing import Section
from app.conflicts import Conflict, find_conflicts

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000 covers the scope in section 2."),
]


# --- DETECT ----------------------------------------------------------------


def test_find_conflicts_returns_the_models_structured_findings(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        # `schema` is built per request (§4.4); its `findings` items are a
        # dynamically-created nested model, not `app.conflicts.Conflict`
        # itself. A dict is what the real SDK hands back too.
        return schema(
            findings=[
                {
                    "section_id": "s3",
                    "quote": "A fixed fee of EUR 48,000",
                    "explanation": "Priced against the old scope.",
                    "blocking": True,
                }
            ]
        )

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    conflicts = find_conflicts(
        sections=SECTIONS, section_id="s2", instruction="Be concrete.", new_text="new text"
    )

    assert conflicts == [
        Conflict(
            section_id="s3", quote="A fixed fee of EUR 48,000",
            explanation="Priced against the old scope.", blocking=True,
        )
    ]


def test_find_conflicts_sends_old_and_new_text_and_the_rest_of_the_document(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["user"] = user
        return schema(findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    find_conflicts(
        sections=SECTIONS, section_id="s2", instruction="Name the deliverables.",
        new_text="Three deliverables, concretely named.",
    )

    assert "EUR 48,000" in captured["user"]           # the rest of the document
    assert "Three deliverables, concretely named." in captured["user"]  # the proposed text
    assert "Name the deliverables." in captured["user"]


def test_find_conflicts_is_pinned_to_temperature_zero(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["temperature"] = kwargs.get("temperature")
        return schema(findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    find_conflicts(sections=SECTIONS, section_id="s2", instruction="x", new_text="y")

    assert captured["temperature"] == 0


def test_the_section_id_field_is_constrained_to_real_ids():
    """The dynamic schema is the whole fix for the old id-repair machinery: the
    model literally cannot return an id that doesn't exist in this document."""
    from pydantic import ValidationError

    from app.conflicts import _conflict_schema

    schema = _conflict_schema(["s1", "s2", "s3"])

    schema(findings=[{"section_id": "s3", "quote": "x", "explanation": "x", "blocking": True}])

    with pytest.raises(ValidationError):
        schema(findings=[{"section_id": "s99", "quote": "x", "explanation": "x", "blocking": True}])

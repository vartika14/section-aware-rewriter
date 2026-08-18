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


# --- ground(): is the conflict real, and is it actually another section? ---

from app.conflicts import Decision, decide, ground, to_notes  # noqa: E402

BY_ID = {s.id: s for s in SECTIONS}


def conflict(**overrides) -> Conflict:
    """A real, blocking conflict against s3 — the shape that should ask."""
    return Conflict(
        **{
            "section_id": "s3",
            "quote": "A fixed fee of EUR 48,000",
            "explanation": "Priced against the old scope.",
            "blocking": True,
            **overrides,
        }
    )


def test_a_quote_lifted_from_the_section_is_grounded():
    assert ground([conflict()], BY_ID, rewritten_id="s2") == [conflict()]


def test_a_quote_that_appears_nowhere_is_dropped():
    assert ground([conflict(quote="a fixed fee of EUR 90,000")], BY_ID, rewritten_id="s2") == []


def test_whitespace_and_case_do_not_defeat_grounding():
    assert ground(
        [conflict(quote="a  FIXED   fee\nof EUR 48,000")], BY_ID, rewritten_id="s2"
    ) == [conflict(quote="a  FIXED   fee\nof EUR 48,000")]


def test_a_conflict_naming_an_unknown_section_is_dropped():
    assert ground([conflict(section_id="s99")], BY_ID, rewritten_id="s2") == []


def test_a_conflict_against_the_rewritten_section_itself_is_dropped():
    """A section cannot conflict with itself — that is just the rewrite. This is
    the direct fix for the old self-reference hole: it cannot be reached here,
    because there is no separate 'resolution' citation left to ground."""
    assert ground([conflict(section_id="s2")], BY_ID, rewritten_id="s2") == []


# --- decide(): the whole interrupt policy -----------------------------------


def test_no_conflicts_completes_silently():
    """The true negative. Precision matters as much as recall."""
    decision = decide([], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert decision.notes == []


def test_a_non_blocking_conflict_completes_as_a_note():
    decision = decide([conflict(blocking=False)], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert [n.section_id for n in decision.notes] == ["s3"]


def test_an_unverified_conflict_never_blocks_but_is_still_reported():
    """A possibly hallucinated conflict must not interrupt anyone — but hiding
    it silently is the class of bug this tool exists to prevent."""
    decision = decide([conflict(quote="not in the document")], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert decision.notes[0].verified is False


def test_a_blocking_grounded_conflict_asks():
    decision = decide([conflict()], SECTIONS, rewritten_id="s2")
    assert decision.action == "ask"
    assert [c.section_id for c in decision.asking] == ["s3"]


def test_conflicts_against_the_same_section_are_all_asked_about_together():
    decision = decide(
        [conflict(), conflict(quote="covers the scope in section 2", explanation="also fee-related")],
        SECTIONS, rewritten_id="s2",
    )
    assert decision.action == "ask"
    assert len(decision.asking) == 2


def test_only_the_first_blocking_section_is_asked_about_the_rest_become_notes():
    """Two blocking conflicts, two different sections: one question, ever — the
    other becomes a note rather than a second interrupt."""
    decision = decide(
        [
            conflict(section_id="s3"),
            conflict(section_id="s1", quote="A recommendation within the quarter"),
        ],
        SECTIONS, rewritten_id="s2",
    )
    assert decision.action == "ask"
    assert {c.section_id for c in decision.asking} == {"s3"}
    assert "s1" in [n.section_id for n in decision.notes]


def test_a_conflict_against_the_rewritten_section_never_blocks():
    decision = decide([conflict(section_id="s2")], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"


def test_a_conflict_against_the_rewritten_section_is_not_shown_as_a_note_either():
    """The model comparing a section's old text to its own new text isn't a
    conflict with another section — it's just the rewrite. It must not reach
    the user at all, not even as a note, the same way ground() already keeps
    it out of the blocking candidates."""
    decision = decide([conflict(section_id="s2")], SECTIONS, rewritten_id="s2")
    assert decision.notes == []


def test_a_conflict_against_the_rewritten_section_stays_out_of_notes_on_the_ask_path_too():
    """Same rule, but this time there's a real, different blocking conflict in
    the same batch — the self-reference must not sneak into the notes that
    accompany the question."""
    decision = decide(
        [conflict(), conflict(section_id="s2")], SECTIONS, rewritten_id="s2"
    )
    assert decision.action == "ask"
    assert "s2" not in [n.section_id for n in decision.notes]

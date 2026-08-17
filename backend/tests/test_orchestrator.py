"""Tests for the suspendable run.

start() may return Asking; resume() (added next task) may not — its return type
is Completed | Declined, which is what makes "at most one question, ever" a fact
about the type checker rather than a fact you have to trust a counter for.
"""

import pytest

from app import orchestrator, store
from app.conflicts import Conflict
from app.parsing import ParsedDocument, Section

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s4", heading="4. Fees and Payment", text="A fixed fee of EUR 48,000 covers it."),
]


@pytest.fixture
def document_id() -> str:
    return store.save_document(ParsedDocument(sections=SECTIONS, headings_detected=True))


@pytest.fixture
def model(monkeypatch):
    """Substitute DRAFT and DETECT; fail the phrasing call on purpose — this
    file asserts on the loop, not on wording."""
    state = {"applicable": True, "new_text": "drafted", "conflicts": []}

    def draft(**kwargs):
        return kwargs["schema"](
            applicable=state["applicable"],
            new_text=state["new_text"] if state["applicable"] else None,
            inapplicable_reason=None if state["applicable"] else "no",
        )

    def detect(**kwargs):
        return kwargs["schema"](
            findings=[c.model_dump() for c in state["conflicts"]]
        )

    monkeypatch.setattr("app.rewrite.structured_completion", draft)
    monkeypatch.setattr("app.conflicts.structured_completion", detect)
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return state


def test_no_conflicts_completes(document_id, model):
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Completed)
    assert outcome.new_text == "drafted"
    assert outcome.notes == []


def test_a_blocking_conflict_suspends(document_id, model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 48,000",
                 explanation="Priced against the old scope.", blocking=True)
    ]
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Asking)
    assert store.get_session(outcome.session_id).section_id == "s2"


def test_an_inapplicable_instruction_declines_before_a_detect_call(document_id, model, monkeypatch):
    model["applicable"] = False
    calls = []
    monkeypatch.setattr(
        "app.conflicts.structured_completion",
        lambda **kw: calls.append(1) or kw["schema"](findings=[]),
    )

    outcome = orchestrator.start(document_id, section_id="s2", instruction="Nonsense here.")

    assert isinstance(outcome, orchestrator.Declined)
    assert calls == []  # DETECT was never called


def test_an_unknown_document_is_not_a_crash(model):
    with pytest.raises(orchestrator.UnknownDocument):
        orchestrator.start("nope", section_id="s1", instruction="x")


def test_an_unknown_section_is_not_a_crash(document_id, model):
    with pytest.raises(orchestrator.UnknownSection):
        orchestrator.start(document_id, section_id="s99", instruction="x")

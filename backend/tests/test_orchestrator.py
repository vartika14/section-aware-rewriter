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


def test_current_texts_reach_the_draft_prompt(document_id, model, monkeypatch):
    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text="drafted")

    monkeypatch.setattr("app.rewrite.structured_completion", draft)

    orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000, renegotiated."},
    )

    assert "A fixed fee of EUR 90,000, renegotiated." in captured["user"]
    assert "A fixed fee of EUR 48,000 covers it." not in captured["user"]


def test_current_texts_reach_the_conflict_check_prompt(document_id, model, monkeypatch):
    captured = {}

    def detect(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", detect)

    orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000, renegotiated."},
    )

    assert "A fixed fee of EUR 90,000, renegotiated." in captured["user"]


def test_leaving_out_current_texts_still_works_as_before(document_id, model):
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")

    assert isinstance(outcome, orchestrator.Completed)


def test_a_pending_question_saves_a_snapshot_of_the_edited_document(document_id, model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 90,000.",
                 explanation="test", blocking=True)
    ]

    outcome = orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000."},
    )

    assert isinstance(outcome, orchestrator.Asking)
    saved = {s.id: s.text for s in store.get_session(outcome.session_id).context}
    assert saved["s4"] == "A fixed fee of EUR 90,000."


from app.question import Branch  # noqa: E402


def asked(document_id: str) -> orchestrator.Asking:
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Asking)
    return outcome


@pytest.fixture
def blocking_model(model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 48,000",
                 explanation="Priced against the old scope.", blocking=True)
    ]
    return model


def test_answering_a_question_uses_the_saved_snapshot_not_the_live_document(
    document_id, model, monkeypatch
):
    """We build a "paused" session by hand here, with a snapshot that
    deliberately says something different from the real document. If
    answering the question uses the snapshot (correct), the fake number shows
    up. If it re-reads the real document instead (wrong), the real number
    shows up."""
    frozen_snapshot = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s4", heading="4. Fees and Payment",
                text="A fixed fee of EUR 999,000, frozen at ask time."),
    ]
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id="s2", instruction="Be concrete.",
            draft_text="drafted", context=frozen_snapshot,
            asking=[Conflict(section_id="s4", quote="A fixed fee of EUR 999,000, frozen at ask time.",
                              explanation="test", blocking=True)],
            notes=[],
        )
    )

    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text="second draft")

    monkeypatch.setattr("app.rewrite.structured_completion", draft)

    orchestrator.resume(session_id, option_key="a")

    assert "A fixed fee of EUR 999,000, frozen at ask time." in captured["user"]
    assert "A fixed fee of EUR 48,000 covers it." not in captured["user"]


def test_holding_produces_a_second_draft(document_id, blocking_model):
    a = asked(document_id)
    blocking_model["new_text"] = "second draft"
    blocking_model["conflicts"] = []   # the re-check finds nothing new

    outcome = orchestrator.resume(a.session_id, option_key="a")

    assert isinstance(outcome, orchestrator.Completed)
    assert outcome.new_text == "second draft"


def test_holding_reports_what_the_recheck_finds_as_a_note_never_a_second_question(
    document_id, blocking_model
):
    a = asked(document_id)
    blocking_model["conflicts"] = [
        Conflict(section_id="s1", quote="A recommendation within the quarter",
                 explanation="No longer supported by the trimmed scope.", blocking=True)
    ]

    outcome = orchestrator.resume(a.session_id, option_key="a")

    assert isinstance(outcome, orchestrator.Completed)  # never Asking — the type already forbids it
    assert "s1" in [n.section_id for n in outcome.notes]


def test_flagging_returns_the_stored_draft_and_keeps_the_finding_as_a_note(document_id, blocking_model):
    a = asked(document_id)
    outcome = orchestrator.resume(a.session_id, option_key="b")

    assert outcome.new_text == "drafted"   # the FIRST draft, untouched
    assert "s4" in [n.section_id for n in outcome.notes]


def test_flagging_calls_the_model_not_at_all(document_id, blocking_model, monkeypatch):
    a = asked(document_id)
    calls = []
    monkeypatch.setattr("app.rewrite.structured_completion", lambda **kw: calls.append(1))

    orchestrator.resume(a.session_id, option_key="b")

    assert calls == []


def test_accepting_returns_the_stored_draft_and_drops_the_finding(document_id, blocking_model):
    a = asked(document_id)
    outcome = orchestrator.resume(a.session_id, option_key="c")

    assert outcome.new_text == "drafted"
    assert outcome.notes == []


def test_a_finished_session_cannot_be_answered_again(document_id, blocking_model):
    a = asked(document_id)
    orchestrator.resume(a.session_id, option_key="c")

    with pytest.raises(orchestrator.SessionFinished):
        orchestrator.resume(a.session_id, option_key="c")


def test_an_unknown_session_is_not_a_crash(blocking_model):
    with pytest.raises(orchestrator.UnknownSession):
        orchestrator.resume("nope", option_key="a")


def test_an_unrecognised_option_is_rejected(document_id, blocking_model):
    a = asked(document_id)
    with pytest.raises(ValueError):
        orchestrator.resume(a.session_id, option_key="z")

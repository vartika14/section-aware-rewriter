"""Tests for the suspendable run.

The clarification loop's judgement lives here — which branch re-drafts, when the
text gets audited again, when the agent stops asking — so it is tested the way
`test_policy.py` tests the interrupt policy: hand-built inputs, no HTTP, no
network. What the endpoint returns is `test_api.py`'s business.

The three branches mean genuinely different things, and the central assertion in
this file is that two of them never go back to the model. An author who clicks
"make the rewrite" and receives different text than the one they were shown has
been given the worst surprise an editing tool has to offer.
"""

import pytest

from app import loop, store
from app.audit import AuditResult, Finding
from app.parsing import ParsedDocument, Section

SECTIONS = [
    Section(
        id="s1",
        heading="1. Executive Summary",
        text="We will deliver a recommendation within the quarter.",
    ),
    Section(
        id="s2",
        heading="2. Scope of Work",
        text="The engagement is advisory; implementation is out of scope.",
    ),
    Section(
        id="s3",
        heading="3. Approach and Timeline",
        text="The engagement runs over eight weeks in three phases.",
    ),
    Section(
        id="s4",
        heading="4. Fees and Payment",
        text="A fixed fee of EUR 48,000 covers the engagement in full. The fee "
        "assumes the scope set out in section 2.",
    ),
]

FIRST_DRAFT = "Three deliverables: a map, a benchmark and a review."
SECOND_DRAFT = "Two deliverables: a map and a benchmark."


def fee_finding(**overrides) -> Finding:
    """Verified and unresolvable — the shape that asks."""
    return Finding(
        **{
            "section_id": "s4",
            "quote": "A fixed fee of EUR 48,000",
            "kind": "invalidated_premise",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


def timeline_finding(**overrides) -> Finding:
    """A second, independent conflict — a different section, so a second group."""
    return Finding(
        **{
            "section_id": "s3",
            "quote": "eight weeks in three phases",
            "kind": "contradiction",
            "explanation": "The new scope names four workstreams, not three.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


def summary_finding(**overrides) -> Finding:
    """A third, on the section a trimmed scope would strand."""
    return Finding(
        **{
            "section_id": "s1",
            "quote": "a recommendation within the quarter",
            "kind": "invalidated_premise",
            "explanation": "The trimmed scope no longer supports the promise.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


@pytest.fixture
def document_id() -> str:
    return store.save_document(
        ParsedDocument(sections=SECTIONS, headings_detected=True)
    )


@pytest.fixture
def model(monkeypatch):
    """Script the pipeline and count what it called.

    `drafts` is a queue: the first draft is popped for round one, the second for
    a branch (a) redraft. `audits` is the same for audit results. `calls` records
    every model call so a test can assert one did NOT happen — which is the point
    of branches (b) and (c). `prompts` keeps what DRAFT was actually sent, so the
    constraint on a second draft can be checked rather than assumed.
    """
    state = {
        "drafts": [FIRST_DRAFT, SECOND_DRAFT],
        "audits": [
            AuditResult(instruction_applicable=True, findings=[fee_finding()]),
            AuditResult(instruction_applicable=True, findings=[]),
        ],
        "calls": [],
        "prompts": [],
    }

    def draft(**kwargs):
        state["calls"].append("draft")
        state["prompts"].append(kwargs["user"])
        return kwargs["schema"](new_text=state["drafts"].pop(0))

    def audit(**kwargs):
        state["calls"].append("audit")
        return state["audits"].pop(0)

    monkeypatch.setattr("app.agent.structured_completion", draft)
    monkeypatch.setattr("app.audit.structured_completion", audit)
    # The phrasing call fails on purpose: these tests assert on the loop, not on
    # how the sentence reads. `test_question.py` owns the wording.
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return state


def ask(document_id: str) -> loop.Asking:
    outcome = loop.start(
        document_id, section_id="s2", instruction="Make this concrete."
    )
    assert isinstance(outcome, loop.Asking)
    return outcome


# --- branch (a): hold the other section ----------------------------------


def test_holding_the_other_section_produces_a_second_draft(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="a")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == SECOND_DRAFT


def test_the_second_draft_is_told_what_it_must_not_break(document_id, model):
    """A constraint the model never sees is a constraint that does nothing.

    Asserted against the prompt DRAFT actually received, not against the session:
    by the time resume returns, `groups` holds the fresh audit's findings, so
    reading it back would test bookkeeping rather than the thing that matters.
    """
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="a")

    second_prompt = model["prompts"][1]
    assert "4. Fees and Payment must stand exactly as written" in second_prompt
    assert "A fixed fee of EUR 48,000" in second_prompt


def test_holding_audits_the_new_text(document_id, model):
    """The text is new and unchecked. Trimming the scope to fit the fee can
    break the summary, which is a conflict that did not exist a moment ago."""
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="a")

    assert model["calls"] == ["draft", "audit", "draft", "audit"]


# --- branches (b) and (c): the draft the author already approved ---------


def test_flagging_returns_the_stored_draft_untouched(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="b")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == FIRST_DRAFT


def test_flagging_calls_the_model_not_at_all(document_id, model):
    """The author said "make the rewrite" — the one they were shown. Going back
    to the model risks returning different text than the text they accepted."""
    asking = ask(document_id)
    model["calls"].clear()

    loop.resume(asking.session_id, option_key="b")

    assert model["calls"] == []


def test_flagging_reports_the_finding_as_a_ripple(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="b")

    assert [ripple.section_id for ripple in outcome.ripples] == ["s4"]
    assert outcome.ripples[0].quote == "A fixed fee of EUR 48,000"


def test_accepting_returns_the_stored_draft_and_says_nothing(document_id, model):
    asking = ask(document_id)
    model["calls"].clear()

    outcome = loop.resume(asking.session_id, option_key="c")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == FIRST_DRAFT
    assert outcome.ripples == []
    assert model["calls"] == []


# --- the answer is recorded, and the session becomes terminal -------------


def test_the_answer_is_recorded_on_the_session(document_id, model):
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="c")

    assert store.get_session(asking.session_id).answers == ["c"]


def test_a_finished_session_cannot_be_answered_again(document_id, model):
    """The stale-tab case: a second click must not re-run the loop."""
    asking = ask(document_id)
    loop.resume(asking.session_id, option_key="c")

    with pytest.raises(loop.SessionFinished):
        loop.resume(asking.session_id, option_key="c")


def test_an_unknown_session_is_not_a_crash(model):
    with pytest.raises(loop.UnknownSession):
        loop.resume("nope", option_key="a")


def test_an_unrecognised_option_is_rejected(document_id, model):
    asking = ask(document_id)

    with pytest.raises(ValueError):
        loop.resume(asking.session_id, option_key="z")


def test_a_failed_redraft_does_not_consume_the_answer(document_id, model, monkeypatch):
    """A 502 mid-resume must leave the session retryable, not half-spent."""
    asking = ask(document_id)

    def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr("app.agent.structured_completion", boom)

    with pytest.raises(RuntimeError):
        loop.resume(asking.session_id, option_key="a")

    session = store.get_session(asking.session_id)
    assert session.answers == []
    assert session.completed is False


# --- a second round, and then no more ------------------------------------


def test_a_leftover_group_becomes_the_second_question(document_id, model):
    """Two conflicts in two sections: one is asked now, one waits its turn."""
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding()],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")

    assert isinstance(second, loop.Asking)
    assert "3. Approach and Timeline" in second.question.text


def test_a_conflict_the_answer_created_becomes_the_second_question(document_id, model):
    """Hold the fee, trim the scope to fit — and now the summary is wrong.

    That conflict did not exist when the first question was asked. Only a fresh
    audit finds it, which is the whole argument for re-auditing after (a).
    """
    model["audits"] = [
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
        AuditResult(instruction_applicable=True, findings=[summary_finding()]),
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="a")

    assert isinstance(second, loop.Asking)
    assert "1. Executive Summary" in second.question.text


def test_the_same_section_is_never_asked_about_twice(document_id, model):
    """A redraft can fail its constraint and hand back the identical finding.
    Re-asking would tell the author the tool was not listening."""
    model["audits"] = [
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
    ]

    asking = ask(document_id)
    outcome = loop.resume(asking.session_id, option_key="a")

    assert isinstance(outcome, loop.Completed)
    assert [ripple.section_id for ripple in outcome.ripples] == ["s4"]


def test_two_questions_is_the_limit(document_id, model):
    """Three conflicts, three sections, and still only two questions."""
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding(), summary_finding()],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")
    assert isinstance(second, loop.Asking)

    third_outcome = loop.resume(second.session_id, option_key="c")
    assert isinstance(third_outcome, loop.Completed)


def test_what_the_cap_decided_is_stated_not_buried(document_id, model):
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding(), summary_finding()],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")
    final = loop.resume(second.session_id, option_key="c")

    assert final.assumptions == [
        "Proceeding with the rewrite; 1. Executive Summary left as it stands."
    ]


def test_a_session_that_asks_again_is_not_yet_finished(document_id, model):
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding()],
        )
    ]

    asking = ask(document_id)
    loop.resume(asking.session_id, option_key="c")

    assert store.get_session(asking.session_id).completed is False

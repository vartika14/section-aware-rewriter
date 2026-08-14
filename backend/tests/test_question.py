"""Tests for how the clarification question gets worded.

The split under test: Python decides what the branches are, the model only makes
the prose read like a colleague wrote it. The model is never allowed to invent,
drop or renumber an option — if it tries, the deterministic wording is used
instead. That keeps the graded judgement in code that can be tested offline while
the consultant still reads a sentence rather than a template.
"""

from app.audit import Finding
from app.parsing import Section
from app.policy import FindingGroup
from app.question import Option, build_options, compose_question

SECTIONS = [
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(
        id="s4",
        heading="4. Fees and Payment",
        text="A fixed fee of EUR 48,000 covers the engagement in full. The fee "
        "assumes the scope set out in section 2.",
    ),
]


def group(*findings: Finding) -> FindingGroup:
    return FindingGroup(
        section_id="s4",
        heading="4. Fees and Payment",
        findings=list(findings)
        or [
            Finding(
                section_id="s4",
                quote="A fixed fee of EUR 48,000",
                kind="invalidated_premise",
                explanation="The fee was priced against the old, vaguer scope.",
                resolvable_from_document=False,
            )
        ],
    )


def no_model(*, system, user, schema, **kwargs):
    raise AssertionError("the deterministic path must not call the model")


# --- the branches are Python's, not the model's --------------------------


def test_the_branches_are_the_three_ways_out_of_a_conflict():
    options = build_options(group())

    assert [option.key for option in options] == ["a", "b", "c"]


def test_every_branch_names_the_section_it_would_affect():
    """A branch a consultant cannot act on is not a branch."""
    for option in build_options(group()):
        assert "4. Fees and Payment" in option.label


def test_the_branches_do_not_depend_on_the_model_being_reachable():
    options = build_options(group())
    again = build_options(group())

    assert options == again


# --- the question itself -------------------------------------------------


def test_the_question_quotes_the_clause_it_is_worried_about(monkeypatch):
    """Naming the exact words is what separates a useful question from
    'this may affect pricing, continue?'."""
    monkeypatch.setattr("app.question.structured_completion", no_model)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables.", polish=False
    )

    assert "A fixed fee of EUR 48,000" in question.text


def test_the_question_covers_every_finding_in_the_group(monkeypatch):
    """Two consequences on one clause are one question, but the human still has
    to be told about both of them."""
    monkeypatch.setattr("app.question.structured_completion", no_model)

    question = compose_question(
        group(
            Finding(
                section_id="s4",
                quote="A fixed fee of EUR 48,000",
                kind="invalidated_premise",
                explanation="The fee was priced against the old scope.",
                resolvable_from_document=False,
            ),
            Finding(
                section_id="s4",
                quote="covers the engagement in full",
                kind="contradiction",
                explanation="The rewrite adds work beyond the original engagement.",
                resolvable_from_document=False,
            ),
        ),
        sections=SECTIONS,
        instruction="Name the deliverables.",
        polish=False,
    )

    assert "priced against the old scope" in question.text
    assert "beyond the original engagement" in question.text


def test_the_question_does_not_merely_re_ask_the_instruction(monkeypatch):
    monkeypatch.setattr("app.question.structured_completion", no_model)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables.", polish=False
    )

    assert "name the deliverables" not in question.text.lower()


# --- the model polishes, but cannot take the wheel -----------------------


def test_polished_wording_is_used_when_it_keeps_the_branches(monkeypatch):
    def polish(*, system, user, schema, **kwargs):
        return schema(
            text='4. Fees and Payment commits to "A fixed fee of EUR 48,000", '
            "priced against the scope you are changing. How should I proceed?",
            options=[
                Option(key="a", label="Keep the fee, scope the rewrite to fit"),
                Option(key="b", label="Rewrite, and flag the fee for review"),
                Option(key="c", label="Rewrite, and accept the mismatch"),
            ],
        )

    monkeypatch.setattr("app.question.structured_completion", polish)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables."
    )

    assert question.text.startswith("4. Fees and Payment commits to")
    assert question.options[1].label == "Rewrite, and flag the fee for review"


def test_wording_that_renumbers_the_branches_is_discarded(monkeypatch):
    """The keys are the contract with the front end and with the resume step. A
    model that returns different ones has changed the decision, not the prose."""

    def rogue(*, system, user, schema, **kwargs):
        return schema(
            text="Which would you prefer?",
            options=[
                Option(key="x", label="Keep the fee"),
                Option(key="y", label="Flag it"),
            ],
        )

    monkeypatch.setattr("app.question.structured_completion", rogue)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables."
    )

    assert [option.key for option in question.options] == ["a", "b", "c"]
    assert "A fixed fee of EUR 48,000" in question.text


def test_wording_that_drops_the_quote_is_discarded(monkeypatch):
    """Observed against the real model: the polish step returned a fluent
    sentence that quoted nothing and referred to the section by its internal id.
    A question that does not name the clause it is worried about is the vague
    warning this design exists to avoid, however well it reads."""

    def unquoted(*, system, user, schema, **kwargs):
        return schema(
            text="The rewrite makes section 5's reference slightly outdated. "
            "How would you like to handle this inconsistency?",
            options=build_options(group()),
        )

    monkeypatch.setattr("app.question.structured_completion", unquoted)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables."
    )

    assert "A fixed fee of EUR 48,000" in question.text


def test_wording_is_kept_when_it_preserves_any_one_quote(monkeypatch):
    """Two findings, one quote carried through — the model is allowed to lead
    with whichever clause it judges most legible."""

    def partial(*, system, user, schema, **kwargs):
        return schema(
            text='Section 4 commits to "A fixed fee of EUR 48,000" priced '
            "against the scope you are changing. How should I proceed?",
            options=build_options(group()),
        )

    monkeypatch.setattr("app.question.structured_completion", partial)

    question = compose_question(
        group(
            Finding(
                section_id="s4",
                quote="A fixed fee of EUR 48,000",
                kind="invalidated_premise",
                explanation="Priced against the old scope.",
                resolvable_from_document=False,
            ),
            Finding(
                section_id="s4",
                quote="covers the engagement in full",
                kind="contradiction",
                explanation="The rewrite adds work.",
                resolvable_from_document=False,
            ),
        ),
        sections=SECTIONS,
        instruction="Name the deliverables.",
    )

    assert question.text.startswith("Section 4 commits to")


def test_a_model_failure_falls_back_to_the_deterministic_question(monkeypatch):
    """Phrasing is a nicety. Losing it must not lose the question."""

    def explode(*, system, user, schema, **kwargs):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("app.question.structured_completion", explode)

    question = compose_question(
        group(), sections=SECTIONS, instruction="Name the deliverables."
    )

    assert "A fixed fee of EUR 48,000" in question.text
    assert [option.key for option in question.options] == ["a", "b", "c"]

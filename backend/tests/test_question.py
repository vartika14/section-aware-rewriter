"""Tests for turning `decide()`'s grouped findings into an answerable question.

No AI call happens here — each section's row is built straight from Python:
heading, quotes, explanation, three lettered options.
"""

from app.conflicts import Conflict, ConflictGroup
from app.question import Branch, build_options, build_question

HEADING = "4. Fees and Payment"


def conflict(**overrides) -> Conflict:
    return Conflict(
        **{
            "section_id": "s4",
            "quote": "A fixed fee of EUR 48,000",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "blocking": True,
            **overrides,
        }
    )


def group(**overrides) -> ConflictGroup:
    return ConflictGroup(
        **{
            "section_id": "s4",
            "heading": HEADING,
            "conflicts": [conflict()],
            **overrides,
        }
    )


# --- the branches are Python's, generated per section ---------------------


def test_the_branches_are_the_three_ways_out_of_a_conflict():
    options = build_options([conflict()], heading=HEADING)

    assert [option.key for option in options] == ["a", "b", "c"]


def test_every_branch_names_the_section_it_would_affect():
    """A branch a consultant cannot act on is not a branch."""
    for option in build_options([conflict()], heading=HEADING):
        assert HEADING in option.label


def test_the_branches_do_not_depend_on_the_model_being_reachable():
    assert build_options([conflict()], heading=HEADING) == build_options(
        [conflict()], heading=HEADING
    )


def test_each_branch_key_has_a_name_the_resume_path_can_switch_on():
    """`orchestrator.py` must not switch on a bare "a". The meaning lives in one place."""
    assert Branch.HOLD.value == "a"
    assert Branch.FLAG.value == "b"
    assert Branch.ACCEPT.value == "c"


def test_the_branch_keys_and_the_rendered_options_cannot_drift_apart():
    assert [option.key for option in build_options([conflict()], heading=HEADING)] == [
        branch.value for branch in Branch
    ]


def test_an_unrecognised_key_is_not_a_branch():
    import pytest

    with pytest.raises(ValueError):
        Branch("z")


# --- build_question(): one row per group ------------------------------------


def test_one_group_becomes_one_row():
    question = build_question([group()])

    assert len(question.groups) == 1
    assert question.groups[0].section_id == "s4"
    assert question.groups[0].heading == HEADING


def test_each_row_keeps_its_own_conflicts_and_options():
    question = build_question(
        [group(conflicts=[conflict(), conflict(quote="covers the engagement in full")])]
    )

    row = question.groups[0]
    assert len(row.conflicts) == 2
    assert [o.key for o in row.options] == ["a", "b", "c"]


def test_two_groups_become_two_independent_rows():
    """The point of this whole design: Fees and Timeline both get a row, each
    answerable on its own, rather than one interrupt now and a second later."""
    question = build_question(
        [
            group(section_id="s4", heading="4. Fees and Payment"),
            group(
                section_id="s5",
                heading="5. Timeline",
                conflicts=[conflict(section_id="s5", quote="four phases of four weeks each")],
            ),
        ]
    )

    assert [row.section_id for row in question.groups] == ["s4", "s5"]
    assert question.groups[1].heading == "5. Timeline"
    assert "four phases of four weeks each" in question.groups[1].conflicts[0].quote


def test_rows_preserve_the_order_they_were_given_in():
    question = build_question(
        [
            group(section_id="s5", heading="5. Timeline"),
            group(section_id="s4", heading="4. Fees and Payment"),
        ]
    )

    assert [row.section_id for row in question.groups] == ["s5", "s4"]

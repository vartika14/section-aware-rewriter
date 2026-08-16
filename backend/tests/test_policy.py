"""Tests for the interrupt policy.

This is the part of the system Sherpa said the session would mostly be about, so
it is deterministic Python and tested exhaustively against hand-built findings —
no network, no model, no flake. Every branch of "should this interrupt a human?"
is pinned here.

The findings below are hand-built rather than recorded from the model because the
policy's job is to be correct about inputs the model might produce, including
dishonest ones.
"""

from app.audit import AuditResult, Finding
from app.parsing import Section
from app.policy import decide, is_blocking, is_resolvable, is_verified

SECTIONS = [
    Section(
        id="s1",
        heading="1. Executive Summary",
        text="We will deliver a recommendation the leadership team can act on "
        "within the quarter.",
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
        text="A fixed fee of EUR 48,000 covers the engagement in full, invoiced "
        "in three instalments. The fee assumes the scope set out in section 2 "
        "and no more than twelve stakeholder interviews.",
    ),
]

BY_ID = {section.id: section for section in SECTIONS}


def finding(**overrides) -> Finding:
    """A verified, unresolvable premise conflict — the shape that should ask."""
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


def resolvable_finding(**overrides) -> Finding:
    """A conflict the document settles by itself: the fee caps interviews."""
    return finding(
        **{
            "kind": "contradiction",
            "quote": "no more than twelve stakeholder interviews",
            "resolvable_from_document": True,
            "deriving_section_id": "s4",
            "deriving_quote": "no more than twelve stakeholder interviews",
            "proposed_fix": "Hold the interview count at twelve.",
            **overrides,
        }
    )


# --- verification: is the conflict itself real? --------------------------


def test_a_quote_lifted_from_the_section_verifies():
    assert is_verified(finding(), BY_ID) is True


def test_verification_ignores_whitespace_and_case():
    """Reformatting is not hallucination. Only invention is."""
    assert is_verified(finding(quote="a  FIXED   fee\nof EUR 48,000"), BY_ID) is True


def test_a_quote_that_appears_nowhere_does_not_verify():
    assert is_verified(finding(quote="a fixed fee of EUR 90,000"), BY_ID) is False


def test_a_quote_attributed_to_an_unknown_section_does_not_verify():
    assert is_verified(finding(section_id="s99"), BY_ID) is False


def test_a_quote_from_the_wrong_section_does_not_verify():
    """The words exist in the document, but not where the finding says."""
    assert is_verified(finding(section_id="s1"), BY_ID) is False


# --- resolvability: is the proposed fix grounded? ------------------------


def test_a_finding_claiming_no_resolution_is_not_resolvable():
    assert is_resolvable(finding(), BY_ID) is False


def test_a_grounded_citation_makes_a_finding_resolvable():
    assert is_resolvable(resolvable_finding(), BY_ID) is True


def test_claiming_resolvable_without_naming_a_section_fails_closed():
    """The model says the document settles it but cannot say where. Ask."""
    assert is_resolvable(resolvable_finding(deriving_section_id=None), BY_ID) is False


def test_claiming_resolvable_without_a_quote_fails_closed():
    assert is_resolvable(resolvable_finding(deriving_quote=None), BY_ID) is False


def test_claiming_resolvable_from_an_unknown_section_fails_closed():
    assert is_resolvable(resolvable_finding(deriving_section_id="s99"), BY_ID) is False


def test_a_derivation_quote_that_is_not_in_that_section_fails_closed():
    """The single most dangerous input: a confident, invented justification for
    not asking the human. It must not be trusted."""
    assert (
        is_resolvable(
            resolvable_finding(deriving_quote="interviews are capped at eighteen"),
            BY_ID,
        )
        is False
    )


# --- the interrupt policy itself -----------------------------------------


def test_an_unresolvable_premise_conflict_blocks():
    """Only the author knows whether a fixed fee still holds."""
    assert is_blocking(finding(), BY_ID) is True


def test_an_unresolvable_contradiction_blocks():
    assert is_blocking(finding(kind="contradiction"), BY_ID) is True


def test_a_stale_reference_to_prose_does_not_block():
    """A page-one summary drifting out of date is a ripple edit, not a decision."""
    stale = finding(
        section_id="s1",
        quote="a recommendation the leadership team can act on",
        kind="stale_reference",
    )

    assert is_blocking(stale, BY_ID) is False


def test_a_stale_reference_to_money_is_not_taken_at_face_value():
    """Measured against the real model: asked about a fixed fee whose premise had
    moved, it labelled the finding `stale_reference` on a third of runs, which
    would have routed it straight past the policy in silence.

    `kind` is the model's opinion. Money is not a description of anything, so a
    quote carrying a commitment cannot be dismissed as merely out of date."""
    mislabelled = finding(kind="stale_reference")  # quotes the EUR 48,000 fee

    assert is_blocking(mislabelled, BY_ID) is True


def test_a_stale_reference_to_a_stated_cap_is_not_taken_at_face_value():
    mislabelled = finding(
        quote="no more than twelve stakeholder interviews", kind="stale_reference"
    )

    assert is_blocking(mislabelled, BY_ID) is True


def test_a_mislabelled_commitment_the_document_settles_still_does_not_block():
    """Overriding the label must not override the rest of the policy: if the
    document answers it, it is still resolved rather than asked about."""
    assert is_blocking(resolvable_finding(kind="stale_reference"), BY_ID) is False


def test_a_resolvable_conflict_does_not_block():
    """The document answers it. Resolve it and show the user; do not ask."""
    assert is_blocking(resolvable_finding(), BY_ID) is False


def test_an_unverified_conflict_never_blocks():
    """The opposite fail direction: an ungrounded conflict may be invented, and
    interrupting a consultant about an imaginary problem is the failure mode the
    brief warns about. It is still reported, just never as a question."""
    assert is_blocking(finding(quote="a fixed fee of EUR 90,000"), BY_ID) is False


# --- decide(): the whole policy end to end -------------------------------


def audit(**overrides) -> AuditResult:
    return AuditResult(
        **{"instruction_applicable": True, "findings": [], **overrides}
    )


def test_a_rewrite_that_breaks_nothing_completes_silently():
    """The true negative. Precision matters as much as recall: an agent that
    always finds something to ask about gets switched off."""
    decision = decide(audit(), SECTIONS, rewritten_section_id="s2")

    assert decision.action == "complete"
    assert decision.ripples == []
    assert decision.groups == []


def test_an_inapplicable_instruction_declines_instead_of_guessing():
    decision = decide(
        audit(
            instruction_applicable=False,
            inapplicable_reason="That section sets no dates to bring forward.",
        ),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "decline"
    assert "dates" in decision.reason


def test_non_blocking_findings_come_back_as_ripples():
    decision = decide(
        audit(
            findings=[
                finding(
                    section_id="s1",
                    quote="a recommendation the leadership team can act on",
                    kind="stale_reference",
                ),
                resolvable_finding(),
            ]
        ),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "complete"
    assert len(decision.ripples) == 2


def test_a_ripple_carries_its_fix_and_the_heading_a_human_can_navigate_to():
    decision = decide(audit(findings=[resolvable_finding()]), SECTIONS, rewritten_section_id="s2")

    ripple = decision.ripples[0]
    assert ripple.heading == "4. Fees and Payment"
    assert ripple.proposed_fix == "Hold the interview count at twelve."
    assert ripple.verified is True


def test_an_unverified_finding_is_reported_but_marked_unverified():
    """Shown, not hidden — silently dropping something the model flagged is the
    class of bug this tool exists to prevent."""
    decision = decide(
        audit(findings=[finding(quote="a fixed fee of EUR 90,000")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "complete"
    assert decision.ripples[0].verified is False


def test_one_blocking_finding_asks():
    decision = decide(audit(findings=[finding()]), SECTIONS, rewritten_section_id="s2")

    assert decision.action == "ask"
    assert len(decision.groups) == 1
    assert decision.groups[0].section_id == "s4"


def test_findings_against_the_same_section_collapse_into_one_question():
    """The Example A case. Two consequences, one underlying decision — a human
    asked twice about the same clause stops reading at the second."""
    decision = decide(
        audit(
            findings=[
                finding(),
                finding(
                    quote="invoiced in three instalments",
                    explanation="The rewrite adds a fourth phase.",
                ),
            ]
        ),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert len(decision.groups) == 1
    assert len(decision.groups[0].findings) == 2


def test_findings_against_different_sections_stay_separate():
    decision = decide(
        audit(
            findings=[
                finding(),
                finding(
                    section_id="s3",
                    quote="three phases",
                    explanation="The rewrite implies a fourth phase.",
                ),
            ]
        ),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert [group.section_id for group in decision.groups] == ["s4", "s3"]


def test_blocking_and_non_blocking_findings_are_reported_together():
    """Asking about the fee must not swallow the summary that also drifted."""
    decision = decide(
        audit(findings=[finding(), finding(section_id="s1", quote="within the quarter", kind="stale_reference")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "ask"
    assert len(decision.groups) == 1
    assert len(decision.ripples) == 1


# --- the section being rewritten cannot vouch for itself -----------------


def test_a_resolution_grounded_in_the_rewritten_section_is_not_a_resolution():
    """The words doing the resolving are about to be deleted.

    `decide` is handed the document as it stands *before* the rewrite, so a
    citation pointing at the section under edit verifies against text that will
    not survive the change. Trusting it is a silent wrong answer.
    """
    self_grounded = finding(
        resolvable_from_document=True,
        deriving_section_id="s2",
        deriving_quote="The engagement is advisory",
    )

    assert is_resolvable(self_grounded, BY_ID) is True
    assert is_resolvable(self_grounded, BY_ID, rewritten_section_id="s2") is False


def test_a_self_grounded_resolution_falls_closed_to_asking():
    decision = decide(
        audit(
            findings=[
                finding(
                    resolvable_from_document=True,
                    deriving_section_id="s2",
                    deriving_quote="The engagement is advisory",
                )
            ]
        ),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "ask"


def test_a_finding_against_the_rewritten_section_never_blocks():
    """A section cannot conflict with itself; that is just the rewrite."""
    decision = decide(
        audit(findings=[finding(section_id="s2", quote="The engagement is advisory")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "complete"


def test_but_it_is_still_reported_as_a_ripple():
    """Silently dropping it would hide part of the document from the author."""
    decision = decide(
        audit(findings=[finding(section_id="s2", quote="The engagement is advisory")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert [ripple.section_id for ripple in decision.ripples] == ["s2"]

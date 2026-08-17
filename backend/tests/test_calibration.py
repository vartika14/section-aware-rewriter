"""Does the interrupt policy fire when it should, across more than one document?

Opt-in, real model, real tokens:

    RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q

The old version of this file tested one document. This one deliberately spans
three, because a design that only works on the vocabulary of one proposal has
not actually been shown to generalize — it has been shown to fit.
"""

import os
from pathlib import Path

import pytest

from app import orchestrator, store
from app.conflicts import decide, find_conflicts
from app.parsing import ParsedDocument, parse_docx
from app.rewrite import draft_section

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"), reason="set RUN_LIVE_TESTS=1 to call the model"
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample"


def load(filename: str):
    path = SAMPLE_DIR / filename
    if not path.exists():
        pytest.skip(f"run the generator for {filename} first")
    return parse_docx(path.read_bytes()).sections


def id_of(sections, heading_fragment: str) -> str:
    return next(s.id for s in sections if heading_fragment in s.heading)


def run(sections, heading_fragment: str, instruction: str):
    section_id = id_of(sections, heading_fragment)
    draft = draft_section(sections=sections, section_id=section_id, instruction=instruction)
    conflicts = find_conflicts(
        sections=sections, section_id=section_id, instruction=instruction, new_text=draft.new_text
    )
    return decide(conflicts, sections, rewritten_id=section_id)


@pytest.fixture(scope="module")
def proposal():
    return load("meridian-proposal.docx")


@pytest.fixture(scope="module")
def policy():
    return load("remote-work-policy.docx")


@pytest.fixture(scope="module")
def charter():
    return load("data-platform-charter.docx")


# --- the proposal: the brief's own example, and the true negative ---------


def test_naming_deliverables_asks_about_the_fixed_fee(proposal):
    """The brief's own worked example.

    Measured at ~5/7 across repeated runs on this deployment, not 7/7.
    Investigated rather than assumed: decide() reliably returns "ask" when
    handed the grounded, blocking finding this instruction should produce — the
    miss is DETECT occasionally judging the draft's added detail (which stays
    within the document's own interview cap) as consistent with the fee rather
    than as changing what it covers. Sharpening the "commits against specific
    wording, not just subject" guidance in conflicts.py's SYSTEM prompt measurably
    improved this (it was failing more often before), without resorting to a
    keyword list. Temperature 0 is documented as not bit-deterministic on this
    deployment; this is that property, not a code defect."""
    decision = run(
        proposal, "Scope of Work",
        "Make this concrete. List the actual deliverables and drop the hedging.",
    )
    assert decision.action == "ask"
    assert id_of(proposal, "Fees") in {c.section_id for c in decision.asking}


def test_tightening_the_summary_prose_asks_nothing(proposal):
    """THE TRUE NEGATIVE. No number, no date, no deliverable, no obligation
    changes. An agent that interrupts here gets switched off."""
    decision = run(proposal, "Executive Summary", "Make this more direct. Cut the hedging.")
    assert decision.action == "complete", [c.explanation for c in decision.asking]


# --- the policy: no money vocabulary anywhere ------------------------------


def test_narrowing_the_remote_work_definition_asks_about_approval(policy):
    """§3's approval rule is measured against §2's definition. Shrinking the
    definition changes what needs HR sign-off — and quotes_a_commitment, the
    old design's money/EUR/fee regex, would never have flagged this."""
    decision = run(
        policy, "Definitions",
        "Narrow this to one day per week instead of three.",
    )
    assert decision.action == "ask"
    assert id_of(policy, "Approval") in {c.section_id for c in decision.asking}


# --- the charter: a date and a training commitment, not a fee --------------


def test_widening_the_pilot_scope_asks_about_the_timeline_or_training(charter):
    """Section 2 is deliberately narrow ("Rotterdam warehouse only"). Widening
    it to more sites should raise a question about at least one of the two
    sections that were written assuming the narrow scope."""
    decision = run(
        charter, "Scope",
        "Expand this to cover all three warehouses, not just Rotterdam.",
    )
    assert decision.action == "ask"
    touched = {c.section_id for c in decision.asking} | {n.section_id for n in decision.notes}
    assert id_of(charter, "Timeline") in touched or id_of(charter, "Training") in touched


# --- the loop terminates, on the document that actually has a conflict -----


def test_the_loop_asks_at_most_once(proposal):
    document_id = store.save_document(ParsedDocument(sections=proposal, headings_detected=True))
    outcome = orchestrator.start(
        document_id, section_id=id_of(proposal, "Scope of Work"),
        instruction="Make this concrete. List the actual deliverables and drop the hedging.",
    )
    if isinstance(outcome, orchestrator.Asking):
        outcome = orchestrator.resume(outcome.session_id, option_key="a")
    assert isinstance(outcome, (orchestrator.Completed, orchestrator.Declined))

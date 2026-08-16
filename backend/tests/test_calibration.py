"""Does the policy fire when it should, and stay quiet when it shouldn't?

These are the only tests that call the real model, so they are opt-in:

    RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q

Everything else in the suite runs offline in seconds. These take a minute and
cost tokens, and they are the ones that would catch a prompt change quietly
turning the agent paranoid — or blind.

The fourth case is the important one. Detection is easy to demonstrate and easy
to fake by asking about everything; the true negative is what shows the thing is
calibrated rather than merely anxious.
"""

import os
from pathlib import Path

import pytest

from app.audit import audit_rewrite
from app.agent import draft_rewrite
from app.parsing import parse_docx
from app.policy import decide

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"), reason="set RUN_LIVE_TESTS=1 to call the model"
)

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "meridian-proposal.docx"


@pytest.fixture(scope="module")
def sections():
    if not SAMPLE.exists():
        pytest.skip("run `python -m scripts.make_sample_docx` first")
    return parse_docx(SAMPLE.read_bytes()).sections


def id_of(sections, heading_fragment: str) -> str:
    """Resolve a section by its heading.

    Ids are positional, and the sample's title line takes `s1` as an untitled
    opening — so every numbered section sits one id further down than its own
    number suggests. Hardcoding ids here silently pointed three of these tests
    at the wrong sections, so they are looked up by name instead.
    """
    return next(s.id for s in sections if heading_fragment in s.heading)


def run(sections, heading_fragment: str, instruction: str):
    section_id = id_of(sections, heading_fragment)
    draft = draft_rewrite(
        sections=sections, section_id=section_id, instruction=instruction
    )
    audit = audit_rewrite(
        sections=sections,
        section_id=section_id,
        instruction=instruction,
        new_text=draft.new_text,
    )
    return decide(audit, sections, rewritten_section_id=section_id)


def flagged_sections(decision) -> set[str]:
    return {group.section_id for group in decision.groups} | {
        ripple.section_id for ripple in decision.ripples
    }


def test_naming_deliverables_asks_about_the_fixed_fee(sections):
    """The brief's own example. Fees prices a fixed fee "for the scope set out in
    section 2", so making the scope concrete changes what that fee covers — and
    only the consultant knows whether it still holds."""
    decision = run(
        sections,
        "Scope of Work",
        "Make this concrete. List the actual deliverables and drop the hedging.",
    )
    fees = id_of(sections, "Fees")

    assert decision.action == "ask"
    assert fees in {group.section_id for group in decision.groups}


def test_adding_a_phase_asks_about_the_fee_and_fixes_the_instalments(sections):
    """Two consequences with different answers. The instalment count is written
    in the document — three phases, three instalments — so the agent should fix
    it rather than ask. Whether the fee survives a fourth phase is not."""
    decision = run(
        sections,
        "Approach and Timeline",
        "Add a fourth phase for implementation support after week eight.",
    )

    assert decision.action == "ask"
    assert id_of(sections, "Fees") in flagged_sections(decision)


def test_exceeding_a_cap_the_document_states_is_caught(sections):
    """Fees caps interviews at twelve. Asking for eighteen contradicts a number
    that is written down."""
    decision = run(
        sections,
        "Scope of Work",
        "Say we will interview all eighteen system owners individually.",
    )

    assert id_of(sections, "Fees") in flagged_sections(decision)


def test_tightening_the_summary_prose_asks_nothing(sections):
    """THE TRUE NEGATIVE. Cutting hedging from the summary changes no number, no
    date, no deliverable and no obligation. An agent that interrupts here is one
    a consultant switches off."""
    decision = run(
        sections,
        "Executive Summary",
        "Make this more direct. Cut the hedging and tighten the prose.",
    )

    assert decision.action == "complete", (
        "asked a question about a pure prose edit: "
        f"{[f.explanation for g in decision.groups for f in g.findings]}"
    )

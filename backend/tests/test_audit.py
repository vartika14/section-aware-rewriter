"""Tests for the audit step.

The audit is the second model call: it is handed the old section, the proposed
replacement and the rest of the document, and asked what breaks. It is framed
neutrally on purpose — a model told it is reviewing its own work rationalises.

The call itself is substituted here. What is worth testing without a network is
that the audit is *given* what it needs to find a conflict, and that the schema
holds the grounding fields the policy later verifies.
"""

import pytest

from app.audit import AuditResult, Finding, audit_rewrite
from app.parsing import Section

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="Act on it this quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(
        id="s3",
        heading="3. Fees",
        text="A fixed fee of EUR 48,000 covers the scope set out in section 2.",
    ),
]


def clean_audit(**overrides) -> AuditResult:
    return AuditResult(**{"instruction_applicable": True, "findings": [], **overrides})


def test_a_finding_carries_the_quote_that_grounds_it():
    finding = Finding(
        section_id="s3",
        quote="A fixed fee of EUR 48,000",
        kind="invalidated_premise",
        explanation="The fee was priced against the old scope.",
        resolvable_from_document=False,
    )

    assert finding.quote == "A fixed fee of EUR 48,000"
    assert finding.deriving_section_id is None
    assert finding.deriving_quote is None


def test_a_resolvable_finding_can_cite_where_the_answer_comes_from():
    """The hinge of the interrupt policy. A finding claiming the document
    resolves it must be able to say which section does the resolving."""
    finding = Finding(
        section_id="s3",
        quote="no more than twelve stakeholder interviews",
        kind="contradiction",
        explanation="The rewrite promises eighteen interviews; the fee caps them at twelve.",
        resolvable_from_document=True,
        deriving_section_id="s3",
        deriving_quote="no more than twelve stakeholder interviews",
        proposed_fix="Hold the count at twelve.",
    )

    assert finding.deriving_section_id == "s3"
    assert finding.proposed_fix == "Hold the count at twelve."


def test_an_audit_can_report_the_instruction_makes_no_sense_here():
    result = AuditResult(
        instruction_applicable=False,
        inapplicable_reason="That section contains no pricing to make concrete.",
        findings=[],
    )

    assert result.instruction_applicable is False
    assert "pricing" in result.inapplicable_reason


def test_audit_sees_the_old_text_the_new_text_and_the_other_sections(monkeypatch):
    """A conflict is invisible unless all three are in front of the model."""
    captured = {}

    def fake_completion(*, system, user, schema, **kwargs):
        captured["user"] = user
        captured["system"] = system
        return clean_audit()

    monkeypatch.setattr("app.audit.structured_completion", fake_completion)

    audit_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Name the deliverables.",
        new_text="We will deliver a current-state map and a target architecture.",
    )

    assert "The engagement is advisory." in captured["user"]
    assert "current-state map" in captured["user"]
    assert "EUR 48,000" in captured["user"]


def test_audit_does_not_tell_the_model_it_is_reviewing_its_own_output(monkeypatch):
    """Framing matters more than temperature here. A model that knows it wrote
    the replacement defends it; one handed an anonymous diff critiques it."""
    captured = {}

    def fake_completion(*, system, user, schema, **kwargs):
        captured["prompt"] = (system + user).lower()
        return clean_audit()

    monkeypatch.setattr("app.audit.structured_completion", fake_completion)

    audit_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Name the deliverables.",
        new_text="A current-state map.",
    )

    for tell in ["you wrote", "your rewrite", "your draft", "you just", "your own"]:
        assert tell not in captured["prompt"], f"audit prompt gives the game away: {tell}"


def test_audit_is_pinned_to_temperature_zero(monkeypatch):
    """An interrupt policy that fires intermittently cannot be defended or
    tested. The graded judgement is the one call that must be deterministic."""
    captured = {}

    def fake_completion(*, system, user, schema, **kwargs):
        captured["temperature"] = kwargs.get("temperature")
        return clean_audit()

    monkeypatch.setattr("app.audit.structured_completion", fake_completion)

    audit_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Be concrete.",
        new_text="Something concrete.",
    )

    assert captured["temperature"] == 0


# --- repairing what the model actually returns ---------------------------


def audit_returning(finding: Finding, monkeypatch) -> AuditResult:
    monkeypatch.setattr(
        "app.audit.structured_completion",
        lambda **kw: clean_audit(findings=[finding]),
    )
    return audit_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Be concrete.",
        new_text="Something concrete.",
    )


def conflict(**overrides) -> Finding:
    return Finding(
        **{
            "section_id": "s3",
            "quote": "A fixed fee of EUR 48,000",
            "kind": "invalidated_premise",
            "explanation": "The fee was priced against the old scope.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


def test_a_section_id_returned_with_its_heading_attached_is_repaired(monkeypatch):
    """Observed against the real model: asked for a section id, it returned the
    whole rendered header, '3. Fees (s3)'. Left alone that matches no section, so
    every finding failed verification and the agent silently stopped asking
    anything at all. Repair it at the boundary, where untrusted output arrives."""
    result = audit_returning(conflict(section_id="3. Fees (s3)"), monkeypatch)

    assert result.findings[0].section_id == "s3"


def test_a_section_id_given_as_a_bare_heading_is_repaired(monkeypatch):
    result = audit_returning(conflict(section_id="3. Fees"), monkeypatch)

    assert result.findings[0].section_id == "s3"


def test_a_deriving_section_id_is_repaired_too(monkeypatch):
    """The same mistake here would fail closed rather than open — the agent would
    ask about something the document already settles."""
    result = audit_returning(
        conflict(
            resolvable_from_document=True,
            deriving_section_id="3. Fees (s3)",
            deriving_quote="A fixed fee of EUR 48,000",
        ),
        monkeypatch,
    )

    assert result.findings[0].deriving_section_id == "s3"


def test_an_unrecognisable_section_id_is_left_alone(monkeypatch):
    """Not repairable is not the same as repairable to anything. A wrong guess
    here would invent a conflict in a section the model never named."""
    result = audit_returning(conflict(section_id="the pricing annex"), monkeypatch)

    assert result.findings[0].section_id == "the pricing annex"


def test_audit_rejects_an_unknown_section_id():
    with pytest.raises(KeyError):
        audit_rewrite(
            sections=SECTIONS,
            section_id="nope",
            instruction="Be concrete.",
            new_text="...",
        )

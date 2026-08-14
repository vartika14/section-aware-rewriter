"""The interrupt policy: which findings are worth stopping a human for?

Deliberately pure Python. No model call. This is the judgement the assignment is
actually about, and as code it can be read, unit tested, and defended by pointing
at a function; as a prompt it would be a vibe.

The policy in one line:

    block on a real conflict the document cannot settle by itself

Everything below is that sentence made precise — and made suspicious of the
model, which is the only reason `is_verified` exists.
"""

import re
from typing import Literal

from pydantic import BaseModel

from .audit import AuditResult, Finding
from .parsing import Section
from .text import normalize

# Text that commits to something rather than describing something. Deliberately
# narrow: money and explicit caps, the two things that cannot be a mere
# description of another section no matter how the model labels them. Times and
# dates are left out on purpose — a summary mentioning "the quarter" usually is
# just describing the plan, and widening this would cost precision.
COMMITMENT = re.compile(
    r"""
      [€$£]\s?\d                                       # €48,000
    | \b(?:eur|usd|gbp)\s?\d                           # EUR 48,000
    | \b(?:fee|fees|price|pricing|cost|invoiced?|instalments?|installments?)\b
    | \bno\ more\ than\b | \bat\ least\b | \bup\ to\b | \bcapped\ at\b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def quotes_a_commitment(quote: str) -> bool:
    """Does this text promise something, as opposed to describing something?"""
    return COMMITMENT.search(quote) is not None


def _quotes(quote: str | None, section_id: str | None, by_id: dict[str, Section]) -> bool:
    """True when `quote` really does appear in the named section."""
    if not quote or not section_id:
        return False
    section = by_id.get(section_id)
    if section is None:
        return False
    return normalize(quote) in normalize(section.text)


def is_verified(finding: Finding, by_id: dict[str, Section]) -> bool:
    """Does the conflict this finding describes actually exist in the document?

    An unverified finding is one whose quote could not be found where it claimed
    to be — the signature of a hallucinated conflict.
    """
    return _quotes(finding.quote, finding.section_id, by_id)


def is_resolvable(finding: Finding, by_id: dict[str, Section]) -> bool:
    """Can the document settle this without asking anyone?

    The model's `resolvable_from_document` claim is not taken on trust: it must
    cite the section and the exact words that supply the answer, and those words
    must really be there. Anything less fails closed, because this boolean is the
    only thing standing between a conflict and a human never hearing about it.
    """
    if not finding.resolvable_from_document:
        return False
    return _quotes(finding.deriving_quote, finding.deriving_section_id, by_id)


def is_blocking(finding: Finding, by_id: dict[str, Section]) -> bool:
    """The interrupt policy.

    Three ways a finding stays quiet, and they are quiet for different reasons:

    * a stale reference is a ripple edit, never a decision — but the label is
      the model's opinion, and it is only honoured for text that describes
      rather than promises. Measured against the real model, a fixed fee whose
      premise had moved came back labelled `stale_reference` on a third of runs,
      which would have walked it silently past this policy. `kind` alone is
      therefore not enough to buy silence;
    * a resolvable conflict has its answer in the document already;
    * an unverified conflict may not be a conflict at all, and interrupting a
      consultant about an imaginary problem is how a tool like this gets
      switched off. It is still reported — see `Ripple.verified` — but it can
      never become a question.
    """
    if finding.kind == "stale_reference" and not quotes_a_commitment(finding.quote):
        return False
    if not is_verified(finding, by_id):
        return False
    return not is_resolvable(finding, by_id)


class Ripple(BaseModel):
    """A consequence the user is told about but not asked about.

    Carries the heading so the UI can point at somewhere a human can navigate to,
    and `verified` so an ungrounded finding is visibly ungrounded rather than
    quietly presented as fact.
    """

    section_id: str
    heading: str
    quote: str
    kind: str
    explanation: str
    proposed_fix: str | None
    verified: bool


class FindingGroup(BaseModel):
    """Findings that share an answer, and therefore share one question.

    Grouped by the section they conflict with: two consequences landing on the
    same clause are one decision for the author, not two.
    """

    section_id: str
    heading: str
    findings: list[Finding]


class Decision(BaseModel):
    action: Literal["complete", "ask", "decline"]
    ripples: list[Ripple] = []
    groups: list[FindingGroup] = []
    reason: str | None = None


def _ripple(finding: Finding, by_id: dict[str, Section]) -> Ripple:
    section = by_id.get(finding.section_id)
    return Ripple(
        section_id=finding.section_id,
        heading=section.heading if section else finding.section_id,
        quote=finding.quote,
        kind=finding.kind,
        explanation=finding.explanation,
        proposed_fix=finding.proposed_fix,
        verified=is_verified(finding, by_id),
    )


def _group(blocking: list[Finding], by_id: dict[str, Section]) -> list[FindingGroup]:
    """Collapse by conflicting section, preserving the order they were found in."""
    groups: dict[str, list[Finding]] = {}
    for finding in blocking:
        groups.setdefault(finding.section_id, []).append(finding)

    return [
        FindingGroup(
            section_id=section_id,
            heading=by_id[section_id].heading if section_id in by_id else section_id,
            findings=findings,
        )
        for section_id, findings in groups.items()
    ]


def decide(audit: AuditResult, sections: list[Section]) -> Decision:
    """Turn the audit's evidence into one of three outcomes."""
    if not audit.instruction_applicable:
        return Decision(
            action="decline",
            reason=audit.inapplicable_reason
            or "That instruction does not apply to the selected section.",
        )

    by_id = {section.id: section for section in sections}

    blocking = [f for f in audit.findings if is_blocking(f, by_id)]
    quiet = [f for f in audit.findings if not is_blocking(f, by_id)]

    return Decision(
        action="ask" if blocking else "complete",
        ripples=[_ripple(f, by_id) for f in quiet],
        groups=_group(blocking, by_id),
    )

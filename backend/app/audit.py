"""The audit step: what does this rewrite break?

A separate model call from the draft, for two reasons. A model asked to write
and critique in one breath rationalises its own output — and the prompt below is
framed as an anonymous review, never as "check your work", so the model has no
draft of its own to defend.

This call produces evidence, not decisions. Whether any of it is worth
interrupting a human for is decided in `policy.py`, in Python, where it can be
read and tested.
"""

import re
from typing import Literal

from pydantic import BaseModel

from .agent import find_section, render_document
from .llm import structured_completion
from .parsing import Section
from .text import normalize

SYSTEM = """You review a proposed edit to one section of a professional document.

You are given the complete document, one section marked [REWRITE], and a
proposed replacement for that section. Report what the replacement breaks
elsewhere in the document.

Report a finding only when another section actually depends on something the
replacement changed. Three kinds:

- "contradiction": another section states something the replacement now
  contradicts outright (a count, a date, a phase, a boundary).
- "invalidated_premise": another section commits to something — money, a
  deadline, an obligation, an acceptance criterion — that was agreed against the
  OLD wording. The clause still reads fine; what it was priced or promised
  against has moved. A fixed fee that cites the rewritten section, a payment
  schedule keyed to its phases, a guarantee keyed to its deliverables.
- "stale_reference": another section only DESCRIBES or SUMMARISES the rewritten
  one — a page-one overview, a recap — and is now slightly out of date. Nothing
  is committed to; correcting it changes no obligation.

Deciding between the last two: ask what happens if the section is left exactly
as it is. If someone is now owed something different, it is an
invalidated_premise. If a reader is merely told something slightly out of date,
it is a stale_reference. Money, dates and obligations are never stale
references.

For every finding:
- `section_id` must be the bracketed identifier of the section you are flagging,
  exactly as it appears in the document — "s4", never "4. Fees and Payment" and
  never "[s4] 4. Fees and Payment".
- `quote` must be text copied EXACTLY from the section you are flagging. Never
  paraphrase, never quote the replacement text itself.
- `resolvable_from_document` is true ONLY when the document already states the
  correct new value — a cap, a stated number, an explicit rule that settles the
  question with no human input. "No more than twelve interviews" settles an
  interview count. "Three instalments, one per phase" settles an instalment
  count.

  A cross-reference is NOT a resolution. A section saying it "assumes the scope
  set out in section 2" is naming its dependency, not resolving it — that phrase
  is the reason the conflict exists, not the answer to it. Whether a fixed fee
  still holds once the scope it points at has changed is a commercial decision
  only the author can make. Set it false.

  When in doubt, false. A needless question costs a moment; a wrong silent
  answer costs money.
- When `resolvable_from_document` is true you MUST set `deriving_section_id` and
  `deriving_quote` to the section and the exact words that supply the answer,
  and `proposed_fix` to the correction they imply.

Report nothing when the replacement changes no commitment that another section
relies on. An empty findings list is a valid and common answer.

Set `instruction_applicable` to false only when the instruction makes no sense
for the section it was aimed at.
"""


class Finding(BaseModel):
    """One consequence of the rewrite, grounded in text that can be checked.

    `quote` and `deriving_quote` both exist so `policy.py` can verify the model
    against the document rather than trusting it. They fail in opposite
    directions: an unverifiable `quote` means the conflict may be invented and
    must never interrupt anyone, while an unverifiable `deriving_quote` means the
    proposed resolution is ungrounded and the human must be asked after all.
    """

    section_id: str
    quote: str
    kind: Literal["contradiction", "invalidated_premise", "stale_reference"]
    explanation: str
    resolvable_from_document: bool
    deriving_section_id: str | None = None
    deriving_quote: str | None = None
    proposed_fix: str | None = None


class AuditResult(BaseModel):
    """`instruction_applicable` sits here rather than on `Finding` because it is
    not a conflict *with another section* — there is no section id to point at."""

    instruction_applicable: bool
    inapplicable_reason: str | None = None
    findings: list[Finding] = []


def _repair_id(value: str | None, sections: list[Section]) -> str | None:
    """Map whatever the model called a section onto an id that exists.

    Asked for an id, the model will sometimes hand back the whole rendered
    header — "3. Fees (s3)" — or just the heading. Neither matches a section, so
    every finding carrying one fails verification and quietly stops being able
    to interrupt anyone. Repairing here is safe because the quote is still
    verified independently afterwards: a repair to the wrong section makes the
    quote stop matching, which is exactly the outcome that should follow.

    A value that resolves to nothing is left untouched rather than guessed at.
    """
    if value is None or any(section.id == value for section in sections):
        return value

    embedded = re.search(r"\bs\d+\b", value)
    if embedded and any(section.id == embedded.group() for section in sections):
        return embedded.group()

    wanted = normalize(value)
    for section in sections:
        if normalize(section.heading) == wanted:
            return section.id
    return value


def _repair(result: AuditResult, sections: list[Section]) -> AuditResult:
    for finding in result.findings:
        finding.section_id = _repair_id(finding.section_id, sections) or finding.section_id
        finding.deriving_section_id = _repair_id(finding.deriving_section_id, sections)
    return result


def audit_rewrite(
    *, sections: list[Section], section_id: str, instruction: str, new_text: str
) -> AuditResult:
    section = find_section(sections, section_id)

    user = (
        f"{render_document(sections, section_id)}\n\n"
        f"---\n\n"
        f"The section marked [REWRITE] ({section.heading}) is proposed to be "
        f"replaced with:\n\n"
        f"{new_text}\n\n"
        f"---\n\n"
        f"The replacement was written to satisfy this instruction: {instruction}\n\n"
        f"What does the replacement break elsewhere in the document?"
    )

    # Temperature 0: an interrupt policy that fires intermittently can be
    # neither defended in a review nor tested.
    result = structured_completion(
        system=SYSTEM, user=user, schema=AuditResult, temperature=0
    )
    return _repair(result, sections)

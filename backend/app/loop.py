"""The suspendable run.

DRAFT → AUDIT → DECIDE, and then either a result or a question. This module owns
the run and the session that outlives it; `main.py` owns nothing but HTTP.

The split matters because the interesting decisions live here — which branch
re-drafts, when to audit again, when to stop asking — and logic reachable only
through a `TestClient` is logic that does not get tested properly. The run still
suspends by returning, exactly as the design specced: no state machine, no queue.
"""

from pydantic import BaseModel

from . import store
from .agent import draft_rewrite, find_section
from .audit import audit_rewrite
from .policy import Ripple, decide
from .question import Question, compose_question


class UnknownDocument(LookupError):
    """The document is not in the store — never uploaded, or lost to a restart."""


class UnknownSection(LookupError):
    """No section with that id in this document."""


class UnknownSession(LookupError):
    """No suspended rewrite with that id."""


class SessionFinished(RuntimeError):
    """This rewrite already finished. The stale-tab case."""


class Completed(BaseModel):
    """The rewrite stands.

    `ripples` are consequences the policy judged not worth interrupting for.
    `assumptions` are decisions the agent made *instead of* asking, once the
    two-question cap was spent — a separate field rather than another ripple,
    because burying them among proposed edits would hide the one thing the design
    promises to state out loud.
    """

    section_id: str
    old_text: str
    new_text: str
    ripples: list[Ripple] = []
    assumptions: list[str] = []


class Asking(BaseModel):
    """The run suspended. It resumes when the author picks an option."""

    session_id: str
    section_id: str
    question: Question


class Declined(BaseModel):
    """The instruction made no sense for this section, so nothing was written."""

    section_id: str
    reason: str


Outcome = Completed | Asking | Declined


def start(document_id: str, *, section_id: str, instruction: str) -> Outcome:
    """First round: draft, audit, decide."""
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    try:
        section = find_section(document.sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_rewrite(
        sections=document.sections, section_id=section_id, instruction=instruction
    )
    audit = audit_rewrite(
        sections=document.sections,
        section_id=section_id,
        instruction=instruction,
        new_text=draft.new_text,
    )
    decision = decide(audit, document.sections, rewritten_section_id=section_id)

    if decision.action == "decline":
        return Declined(section_id=section.id, reason=decision.reason or "")

    if decision.action == "complete":
        return Completed(
            section_id=section.id,
            old_text=section.text,
            new_text=draft.new_text,
            ripples=decision.ripples,
        )

    # Suspend. One question per round, so the first group is asked now and any
    # others wait — a human asked four questions stops reading at the second.
    asked = decision.groups[0]
    question = compose_question(
        asked, sections=document.sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id,
            section_id=section_id,
            instruction=instruction,
            draft_text=draft.new_text,
            groups=decision.groups,
            ripples=decision.ripples,
            asked_section_ids=[asked.section_id],
        )
    )

    return Asking(session_id=session_id, section_id=section.id, question=question)

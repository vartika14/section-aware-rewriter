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
from .policy import FindingGroup, Ripple, decide, to_ripple
from .question import Branch, Question, compose_question


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


def hold_constraint(group: FindingGroup) -> str:
    """What a second draft is held to when the author says "hold that section".

    Built here rather than asked of the model, so what the redraft must honour is
    a string this file's tests can read. It quotes the clause, because a
    constraint the model has to infer is one it can talk itself out of.
    """
    quotes = " ".join(f'It says "{finding.quote}".' for finding in group.findings)
    return (
        f"{group.heading} must stand exactly as written. {quotes} "
        f"Shape the rewrite so this remains true, and do not contradict it."
    )


def resume(session_id: str, *, option_key: str) -> Outcome:
    """Second half of the loop: the author picked a branch.

    Only one branch of three needs new text. "Hold the other section" is the
    author changing their mind about the rewrite; "flag it" and "leave it" are
    the author approving the draft they were shown, and returning to the model
    there would risk handing back something else.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.completed:
        raise SessionFinished(session_id)

    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # ValueError on anything else, by design
    asked, remaining = session.groups[0], session.groups[1:]
    by_id = {section.id: section for section in document.sections}

    if branch is Branch.HOLD:
        # New text, so it gets audited. The audit is given the ORIGINAL
        # instruction and not the constraint: if the redraft failed to honour the
        # held clause, a neutral reviewer flags it again, which is correct. An
        # audit told what the draft was trying to do is inclined to grant that it
        # succeeded.
        draft = draft_rewrite(
            sections=document.sections,
            section_id=session.section_id,
            instruction=session.instruction,
            constraints=[hold_constraint(asked)],
        )
        audit = audit_rewrite(
            sections=document.sections,
            section_id=session.section_id,
            instruction=session.instruction,
            new_text=draft.new_text,
        )
        # `instruction_applicable` is honoured in `start` and ignored here. Round
        # one already established that the instruction applies; a flip now is far
        # more likely model noise than a real reversal, and acting on it would
        # discard work the author has already answered a question about.
        decision = decide(
            audit, document.sections, rewritten_section_id=session.section_id
        )
        new_text = draft.new_text
        ripples = list(decision.ripples)
        groups = list(decision.groups)
    else:
        # Byte-identical to text that was already audited, so auditing it again
        # would spend a call to ask the same question of the same words.
        new_text = session.draft_text
        ripples = list(session.ripples)
        groups = list(remaining)
        if branch is Branch.FLAG:
            ripples.extend(to_ripple(finding, by_id) for finding in asked.findings)

    # Only now: every model call has returned, so a failure above leaves the
    # session exactly as it was and the author can retry without burning a round.
    session.answers.append(option_key)
    session.draft_text = new_text
    session.ripples = ripples
    session.groups = groups
    session.completed = True

    section = find_section(document.sections, session.section_id)
    return Completed(
        section_id=section.id,
        old_text=section.text,
        new_text=new_text,
        ripples=ripples,
    )

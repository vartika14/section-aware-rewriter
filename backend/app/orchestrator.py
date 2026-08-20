"""Runs one rewrite from start to finish, pausing for a question if needed.

`start()` may pause and ask a question. `resume()` answers it and always
finishes — its return type has no "ask again" option, so a rewrite can never
end up asking a second question.
"""

from pydantic import BaseModel

from . import store
from .conflicts import (
    Conflict,
    Note,
    decide,
    dedupe_notes,
    exclude_self_references,
    find_conflicts,
    ground,
    to_notes,
)
from .question import Branch, Question, build_question
from .rewrite import draft_section, find_section, overlay_texts


class UnknownDocument(LookupError):
    """Not in the store — never uploaded, or lost to a restart."""


class UnknownSection(LookupError):
    """No section with that id in this document."""


class UnknownSession(LookupError):
    """No suspended rewrite with that id."""


class SessionFinished(RuntimeError):
    """This rewrite already finished. The stale-tab case."""


class AnswerMismatch(ValueError):
    """The answer didn't cover exactly the sections being asked about."""


class Completed(BaseModel):
    section_id: str
    old_text: str
    new_text: str
    notes: list[Note] = []


class Asking(BaseModel):
    session_id: str
    section_id: str
    question: Question


class Declined(BaseModel):
    section_id: str
    reason: str


Outcome = Completed | Asking | Declined


def start(
    document_id: str, *, section_id: str, instruction: str,
    current_texts: dict[str, str] | None = None,
) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    # The document as it stands right now: accepted edits filled in,
    # original text everywhere else.
    sections = overlay_texts(document.sections, current_texts or {})

    try:
        section = find_section(sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_section(sections=sections, section_id=section_id, instruction=instruction)

    if not draft.applicable:
        return Declined(
            section_id=section.id,
            reason=draft.inapplicable_reason or "That instruction does not apply to this section.",
        )

    conflicts = find_conflicts(
        sections=sections, section_id=section_id,
        instruction=instruction, new_text=draft.new_text,
    )
    decision = decide(conflicts, sections, rewritten_id=section_id)

    if decision.action == "complete":
        return Completed(
            section_id=section.id, old_text=section.text,
            new_text=draft.new_text, notes=decision.notes,
        )

    question = build_question(decision.asking)
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id=section_id, instruction=instruction,
            draft_text=draft.new_text, context=sections,
            asking=decision.asking, notes=decision.notes,
        )
    )
    return Asking(session_id=session_id, section_id=section.id, question=question)


def hold_constraint(conflicts: list[Conflict], heading: str) -> str:
    """Turn "hold this section" into an instruction the redraft must follow —
    written as plain text so it's easy to check in a test."""
    quotes = " ".join(f'It says "{c.quote}".' for c in conflicts)
    return f"{heading} must stand exactly as written. {quotes} Do not contradict it."


def resume(session_id: str, *, choices: dict[str, str]) -> Completed | Declined:
    """Answer a paused question — one choice per section that was asked about.

    Every held section feeds into a single redraft together, so holding two
    sections costs one extra AI call, not two. Flagged sections need no new
    call — the finding is already known, and a fresh draft the author never
    saw could come back different from what they agreed to. Accepted
    sections need nothing further; the mismatch is simply dropped.

    Can only return a finished result or a decline — never a second question.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.resolved:
        raise SessionFinished(session_id)

    # Confirm the document hasn't disappeared (e.g. a server restart). We
    # don't use its sections for anything else below — the frozen snapshot
    # in session.context is what the question was actually asked against.
    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    asked_ids = {group.section_id for group in session.asking}
    if set(choices) != asked_ids:
        raise AnswerMismatch(
            "Each section being asked about needs exactly one answer — "
            f"expected {sorted(asked_ids)}, got {sorted(choices)}."
        )
    branches = {section_id: Branch(key) for section_id, key in choices.items()}

    by_id = {s.id: s for s in session.context}
    held = [g for g in session.asking if branches[g.section_id] is Branch.HOLD]
    flagged = [g for g in session.asking if branches[g.section_id] is Branch.FLAG]

    notes = session.notes + to_notes(
        [c for g in flagged for c in g.conflicts],
        [c for g in flagged for c in g.conflicts],
        by_id,
    )

    if held:
        constraints = [hold_constraint(g.conflicts, g.heading) for g in held]
        draft = draft_section(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction, constraints=constraints,
        )
        found = find_conflicts(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction, new_text=draft.new_text,
        )
        # A finding against the section we just redrafted isn't a real
        # conflict — it's just the redraft. Same rule decide() applies.
        found = exclude_self_references(found, session.section_id)
        grounded = ground(found, by_id, rewritten_id=session.section_id)
        notes = notes + to_notes(found, grounded, by_id)
        new_text = draft.new_text
    else:
        new_text = session.draft_text

    session.resolved = True
    section = find_section(session.context, session.section_id)
    return Completed(
        section_id=section.id, old_text=section.text, new_text=new_text,
        notes=dedupe_notes(notes),
    )

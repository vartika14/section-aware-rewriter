"""The suspendable run. `start()` may ask one question; `resume()` (next task)
answers it and always finishes — its return type has no `Asking` arm, which is
what makes "at most one question, ever" a property of the type checker.
"""

from pydantic import BaseModel

from . import store
from .conflicts import Conflict, Note, decide, exclude_self_references, find_conflicts, ground, to_notes
from .question import Branch, Question, compose_question
from .rewrite import draft_section, find_section, overlay_texts


class UnknownDocument(LookupError):
    """Not in the store — never uploaded, or lost to a restart."""


class UnknownSection(LookupError):
    """No section with that id in this document."""


class UnknownSession(LookupError):
    """No suspended rewrite with that id."""


class SessionFinished(RuntimeError):
    """This rewrite already finished. The stale-tab case."""


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

    # Build the document as it currently stands: accepted edits filled in,
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

    heading = find_section(sections, decision.asking[0].section_id).heading
    question = compose_question(
        decision.asking, heading=heading, sections=sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id=section_id, instruction=instruction,
            draft_text=draft.new_text, context=sections,
            asking=decision.asking, notes=decision.notes,
        )
    )
    return Asking(session_id=session_id, section_id=section.id, question=question)


def hold_constraint(conflicts: list[Conflict], heading: str) -> str:
    """What a second draft is held to when the author says "hold that section".

    Built here, not asked of the model, so what the redraft must honour is a
    string this file's tests can read.
    """
    quotes = " ".join(f'It says "{c.quote}".' for c in conflicts)
    return f"{heading} must stand exactly as written. {quotes} Do not contradict it."


def resume(session_id: str, *, option_key: str) -> Completed | Declined:
    """Answer a paused question.

    Only one of the three answers ("hold the other section") needs a new
    rewrite. The other two mean "go ahead with what I was already shown" — so
    going back to the model there would risk handing back different text than
    what the author actually agreed to.

    This function can only return a finished result or a "declined" — never a
    second question. That's not a rule we remember to follow; it's built into
    what this function is allowed to return.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.resolved:
        raise SessionFinished(session_id)

    # We still check the document itself hasn't disappeared (say, from a
    # server restart) — that check doesn't change. What changes is that we no
    # longer use this document's sections for anything else below; we use the
    # frozen snapshot instead.
    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # raises a clear error on anything else
    by_id = {s.id: s for s in session.context}
    heading = by_id[session.asking[0].section_id].heading

    if branch is Branch.HOLD:
        draft = draft_section(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction,
            constraints=[hold_constraint(session.asking, heading)],
        )
        found = find_conflicts(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction, new_text=draft.new_text,
        )
        # Same rule decide() applies on a first-round rewrite: a finding
        # against the section being redrafted isn't a conflict with another
        # section, so it must never show up as a note about itself.
        found = exclude_self_references(found, session.section_id)
        grounded = ground(found, by_id, rewritten_id=session.section_id)
        notes = session.notes + to_notes(found, grounded, by_id)
        new_text = draft.new_text
    else:
        new_text = session.draft_text
        notes = session.notes + (
            to_notes(session.asking, session.asking, by_id) if branch is Branch.FLAG else []
        )

    session.resolved = True
    section = find_section(session.context, session.section_id)
    return Completed(section_id=section.id, old_text=section.text, new_text=new_text, notes=notes)

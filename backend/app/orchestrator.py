"""The suspendable run. `start()` may ask one question; `resume()` (next task)
answers it and always finishes — its return type has no `Asking` arm, which is
what makes "at most one question, ever" a property of the type checker.
"""

from pydantic import BaseModel

from . import store
from .conflicts import Note, decide, find_conflicts
from .question import Question, compose_question
from .rewrite import draft_section, find_section


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


def start(document_id: str, *, section_id: str, instruction: str) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    try:
        section = find_section(document.sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_section(sections=document.sections, section_id=section_id, instruction=instruction)

    if not draft.applicable:
        return Declined(
            section_id=section.id,
            reason=draft.inapplicable_reason or "That instruction does not apply to this section.",
        )

    conflicts = find_conflicts(
        sections=document.sections, section_id=section_id,
        instruction=instruction, new_text=draft.new_text,
    )
    decision = decide(conflicts, document.sections, rewritten_id=section_id)

    if decision.action == "complete":
        return Completed(
            section_id=section.id, old_text=section.text,
            new_text=draft.new_text, notes=decision.notes,
        )

    heading = find_section(document.sections, decision.asking[0].section_id).heading
    question = compose_question(
        decision.asking, heading=heading, sections=document.sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id=section_id, instruction=instruction,
            draft_text=draft.new_text, asking=decision.asking, notes=decision.notes,
        )
    )
    return Asking(session_id=session_id, section_id=section.id, question=question)

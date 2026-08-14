"""In-memory state.

Persistence across restarts is explicitly out of scope for this assignment, so
a module-level dict is the honest choice rather than a database that would need
explaining.

Two things live here: uploaded documents, and rewrite runs that suspended
themselves to ask the user a question.
"""

from uuid import uuid4

from pydantic import BaseModel

from .parsing import ParsedDocument
from .policy import FindingGroup, Ripple

_DOCUMENTS: dict[str, ParsedDocument] = {}
_SESSIONS: dict[str, "RewriteSession"] = {}


class RewriteSession(BaseModel):
    """A rewrite that stopped to ask something, and everything needed to finish.

    `draft_text` is kept so the answer resumes from a rewrite that already
    exists rather than re-running the draft blind, and `groups` is kept because
    the answer only means anything against the question it was asked.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    groups: list[FindingGroup]
    ripples: list[Ripple]
    answers: list[str] = []


def save_document(parsed: ParsedDocument) -> str:
    document_id = uuid4().hex[:12]
    _DOCUMENTS[document_id] = parsed
    return document_id


def get_document(document_id: str) -> ParsedDocument | None:
    return _DOCUMENTS.get(document_id)


def save_session(session: RewriteSession) -> str:
    session_id = uuid4().hex[:12]
    _SESSIONS[session_id] = session
    return session_id


def get_session(session_id: str) -> RewriteSession | None:
    return _SESSIONS.get(session_id)

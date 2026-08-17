"""In-memory state.

Persistence across restarts is explicitly out of scope for this assignment, so
a module-level dict is the honest choice rather than a database that would need
explaining.

Two things live here: uploaded documents, and rewrite runs that suspended
themselves to ask the user a question.
"""

from uuid import uuid4

from pydantic import BaseModel

from .conflicts import Conflict, Note
from .parsing import ParsedDocument, Section

_DOCUMENTS: dict[str, ParsedDocument] = {}
_SESSIONS: dict[str, "RewriteSession"] = {}


class RewriteSession(BaseModel):
    """A rewrite that's paused, waiting for the user to answer one question.

    `context` is a snapshot: the document exactly as it looked — including any
    edits the author had already accepted — at the moment the question was
    asked. When the answer comes back, we check it against this snapshot, not
    against whatever the document looks like by then. That way the question
    and the answer are always talking about the exact same document.

    `draft_text` is the rewrite we already produced, so answering the question
    doesn't mean starting over from nothing. `asking` is what the question is
    about. `notes` are things we noticed but decided not to ask about — kept
    here so we can still show them in the final result.

    `resolved` marks a session as finished, so answering it twice (say, from
    an old browser tab) gives a clear error instead of quietly running again.
    There's no "how many times have we asked" counter here, because the app
    only ever asks once.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    context: list[Section]
    asking: list[Conflict]
    notes: list[Note]
    resolved: bool = False


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

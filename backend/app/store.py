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
from .parsing import ParsedDocument

_DOCUMENTS: dict[str, ParsedDocument] = {}
_SESSIONS: dict[str, "RewriteSession"] = {}


class RewriteSession(BaseModel):
    """A rewrite that stopped to ask one question, and everything needed to
    finish it.

    `draft_text` lets the answer resume from the rewrite that already exists
    rather than re-running DRAFT blind. `asking` is the group the pending
    question is about. `notes` are consequences already decided not to ask
    about — kept here so `resume()`'s branches that don't call the model again
    can still return them with the final result.

    `resolved` makes a finished session terminal: a stale tab answering twice
    gets a 409, not a second run of the loop. There is no round counter and no
    per-section suppression list, because there is only ever one round.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
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

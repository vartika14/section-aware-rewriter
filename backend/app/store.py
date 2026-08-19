"""In-memory state: uploaded documents, and rewrites paused on a question.

Nothing here survives a server restart — that's fine for this app, which
doesn't need persistence.
"""

from uuid import uuid4

from pydantic import BaseModel

from .conflicts import ConflictGroup, Note
from .parsing import ParsedDocument, Section

_DOCUMENTS: dict[str, ParsedDocument] = {}
_SESSIONS: dict[str, "RewriteSession"] = {}


class RewriteSession(BaseModel):
    """One rewrite, paused while it waits for the author to answer a question.

    `context` is the document exactly as it looked when the question was
    asked, so the answer is always checked against the same document the
    question was about — not whatever the document looks like by the time
    the author replies.

    `draft_text` is the rewrite already written, so answering doesn't mean
    starting over. `asking` is the question itself, one row per section that
    blocks. `notes` are things noticed but not worth asking about.

    `resolved` stops a session from being answered twice.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    context: list[Section]
    asking: list[ConflictGroup]
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

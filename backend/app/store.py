"""In-memory state.

Persistence across restarts is explicitly out of scope for this assignment, so
a module-level dict is the honest choice rather than a database that would need
explaining. Later phases add suspended rewrite sessions alongside documents.
"""

from uuid import uuid4

from .parsing import ParsedDocument

_DOCUMENTS: dict[str, ParsedDocument] = {}


def save_document(parsed: ParsedDocument) -> str:
    document_id = uuid4().hex[:12]
    _DOCUMENTS[document_id] = parsed
    return document_id


def get_document(document_id: str) -> ParsedDocument | None:
    return _DOCUMENTS.get(document_id)

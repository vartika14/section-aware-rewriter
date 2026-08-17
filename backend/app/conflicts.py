"""DETECT, and the interrupt policy that decides what to do with what it finds.

DETECT is a separate model call from DRAFT, framed as an anonymous review — "here
is a proposed replacement, here is the rest of the document, what does it break?"
— with no hint that it is reading its own output, because a model asked to write
and critique in one breath rationalises.

This call produces evidence. Whether any of it is worth interrupting the author
for is `decide()`, in pure Python, added in the next part of this file.
"""

from typing import Literal

from pydantic import BaseModel, create_model

from .llm import structured_completion
from .parsing import Section
from .rewrite import find_section, render_document
from .text import normalize

SYSTEM = """You review a proposed replacement for one section of a document
against the rest of the document. Report what it breaks elsewhere.

A conflict exists when another section depends on something the replacement
changed — a number, a date, a quantity, a named obligation, a boundary — and that
dependency no longer holds. Merely describing the rewritten section in passing,
with nothing riding on it, is not a conflict.

For every conflict:
- `section_id` names the OTHER section — the one the replacement breaks something
  in — never the section being rewritten.
- `quote` is copied EXACTLY from that other section. Never paraphrase.
- `blocking` is true when only the document's author can settle it — a
  cross-reference alone is not a resolution, it is the reason the conflict
  exists. `blocking` is false when the inconsistency is cosmetic: nothing is
  owed differently, a reader would just see slightly stale wording.

When in doubt, true. A needless question costs a moment; a wrong silent answer
costs the author something real, in whatever this document governs.

Report nothing when the replacement changes no commitment another section
depends on. An empty list is a valid and common answer.
"""


class Conflict(BaseModel):
    """One consequence of the rewrite, in a section other than the one rewritten.

    `blocking` is the model's own judgment, trusted directly — the room this
    design uses for "extra LLM calls for conflict detection" instead of a
    keyword heuristic. Python's only say is `ground()`: is the quote real, and
    is this actually a different section.
    """

    section_id: str
    quote: str
    explanation: str
    blocking: bool


class Note(BaseModel):
    """A conflict the author is told about but not asked about."""

    section_id: str
    heading: str
    quote: str
    explanation: str
    verified: bool


def _conflict_schema(section_ids: list[str]) -> type[BaseModel]:
    """Build the response schema with `section_id` constrained to this
    document's real ids.

    The old design let the model return an id like "4. Fees and Payment (s5)"
    and then tried to repair it after the fact with three fallback strategies.
    A dynamically-built Literal makes that response fail schema validation
    outright — which already has a retry, in `llm.py` — instead of reaching
    application code as something to be guessed back into shape.
    """
    SectionId = Literal[*section_ids]  # PEP 646 star-unpacking
    PerRequestConflict = create_model(
        "Conflict",
        section_id=(SectionId, ...),
        quote=(str, ...),
        explanation=(str, ...),
        blocking=(bool, ...),
    )
    return create_model("DetectResult", findings=(list[PerRequestConflict], ...))


def find_conflicts(
    *, sections: list[Section], section_id: str, instruction: str, new_text: str
) -> list[Conflict]:
    section = find_section(sections, section_id)
    schema = _conflict_schema([s.id for s in sections])

    user = (
        f"{render_document(sections, section_id)}\n\n"
        f"---\n\n"
        f"The section marked [REWRITE] ({section.heading}) is proposed to be "
        f"replaced with:\n\n{new_text}\n\n"
        f"---\n\n"
        f"The replacement was written to satisfy this instruction: {instruction}\n\n"
        f"What does the replacement break elsewhere in the document?"
    )

    result = structured_completion(system=SYSTEM, user=user, schema=schema, temperature=0)
    return [Conflict(**f.model_dump()) for f in result.findings]

"""DETECT: check a proposed rewrite against the rest of the document.

This is a second, separate AI call from DRAFT. It's shown the proposed
replacement as if reviewing someone else's work, not its own — a model asked
to write and critique in the same breath tends to defend its own writing.

DETECT only reports what it found. Deciding whether any of it is worth
interrupting the author for is `decide()`, below — plain Python, no AI call.
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
- A section that commits to something "for", "assuming", or "as defined in"
  another section is committing against that section's specific wording, not
  just its general subject. If the wording changes at all — even by adding
  detail that seems consistent with it — treat the commitment as blocking
  unless you are certain nothing about what is covered or owed has changed.

When in doubt, true. A needless question costs a moment; a wrong silent answer
costs the author something real, in whatever this document governs.

Report nothing when the replacement changes no commitment another section
depends on. An empty list is a valid and common answer.
"""


class Conflict(BaseModel):
    """One consequence of the rewrite, found in a section other than the one
    being rewritten.

    `blocking` is the model's own judgment — we trust it. Python's only job
    is `ground()`, below: checking the quote is real and belongs to a
    different section.
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
    """Build the response schema for this specific document, with
    `section_id` restricted to this document's real ids.

    This makes it impossible for the model to return a made-up or malformed
    id — the API rejects it before our code ever sees it.
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


def ground(
    conflicts: list[Conflict], sections_by_id: dict[str, Section], rewritten_id: str
) -> list[Conflict]:
    """Keep only conflicts whose quote is real — actually present, word for
    word, in the section it claims to be from — and against a section other
    than the one being rewritten. This is the hallucination guard: a made-up
    quote never reaches the author as something to act on.
    """
    grounded = []
    for c in conflicts:
        if c.section_id == rewritten_id:
            continue
        section = sections_by_id.get(c.section_id)
        if section is None:
            continue
        if normalize(c.quote) in normalize(section.text):
            grounded.append(c)
    return grounded


def to_notes(
    conflicts: list[Conflict], grounded: list[Conflict], sections_by_id: dict[str, Section]
) -> list[Note]:
    grounded_set = {(c.section_id, c.quote) for c in grounded}
    return [
        Note(
            section_id=c.section_id,
            heading=sections_by_id[c.section_id].heading
            if c.section_id in sections_by_id else c.section_id,
            quote=c.quote,
            explanation=c.explanation,
            verified=(c.section_id, c.quote) in grounded_set,
        )
        for c in conflicts
    ]


class ConflictGroup(BaseModel):
    """All the blocking conflicts against one section, bundled into one row
    the author answers once — even if DETECT reported several quotes from
    that same section."""

    section_id: str
    heading: str
    conflicts: list[Conflict]


class Decision(BaseModel):
    """What the interrupt policy decided: either ask about every section
    that genuinely blocks (one row each), or complete with no interruption."""

    action: Literal["ask", "complete"]
    asking: list[ConflictGroup] = []
    notes: list[Note] = []


def exclude_self_references(conflicts: list[Conflict], rewritten_id: str) -> list[Conflict]:
    """Drop any finding against the section being rewritten — that's not a
    conflict with another section, it's just the rewrite happening.

    This is its own function because two places need it: `decide()` below,
    and `orchestrator.py`'s `resume()`, which checks a redraft the same way
    but doesn't call `decide()` to do it.
    """
    return [c for c in conflicts if c.section_id != rewritten_id]


def decide(conflicts: list[Conflict], sections: list[Section], rewritten_id: str) -> Decision:
    """The interrupt policy: which findings are worth stopping for.

    A finding that isn't grounded (see `ground()`) never blocks, even if the
    model marked it blocking — an unverified quote isn't trustworthy enough
    to interrupt someone over. Every section left with a blocking finding
    gets its own row in the question, so a rewrite that upsets both Fees and
    Timeline asks about both at once, not one now and one later. Anything
    left over — non-blocking, or ungrounded — becomes a note instead.
    """
    by_id = {s.id: s for s in sections}
    conflicts = exclude_self_references(conflicts, rewritten_id)
    grounded = ground(conflicts, by_id, rewritten_id)
    blocking = [c for c in grounded if c.blocking]

    if not blocking:
        return Decision(action="complete", notes=to_notes(conflicts, grounded, by_id))

    # Keeps sections in the order DETECT reported them, not hash order.
    blocking_section_ids = list(dict.fromkeys(c.section_id for c in blocking))
    groups = [
        ConflictGroup(
            section_id=section_id,
            heading=by_id[section_id].heading,
            conflicts=[c for c in blocking if c.section_id == section_id],
        )
        for section_id in blocking_section_ids
    ]
    non_blocking = [c for c in conflicts if c not in blocking]
    return Decision(
        action="ask", asking=groups, notes=to_notes(non_blocking, grounded, by_id)
    )

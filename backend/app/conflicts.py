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


def ground(
    conflicts: list[Conflict], sections_by_id: dict[str, Section], rewritten_id: str
) -> list[Conflict]:
    """Keep only conflicts whose quote is real, in a section other than the one
    being rewritten.

    Excluding the rewritten section here is what replaces the old design's
    separate self-reference guard: since there is no second "resolution" quote
    left to fail closed on, keeping the section-under-edit out of the candidate
    pool in the first place removes the whole failure mode rather than patching
    it after the fact.
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


class Decision(BaseModel):
    """The whole interrupt policy's output: ask about one thing, or complete."""

    action: Literal["ask", "complete"]
    asking: list[Conflict] = []
    notes: list[Note] = []


def decide(conflicts: list[Conflict], sections: list[Section], rewritten_id: str) -> Decision:
    """Ungrounded conflicts never block — a possibly hallucinated conflict must
    not interrupt anyone, the same asymmetry the old design measured and kept.

    Only the FIRST blocking section is ever asked about. Everything else this
    round — a different blocking section, or a non-blocking finding — becomes a
    note instead. This is the entire reason "at most one question, ever" needs
    no counter: there is only ever one group to ask about, by construction.
    """
    by_id = {s.id: s for s in sections}
    # A finding against the section being rewritten isn't a conflict with
    # another section at all — it's just the rewrite. Drop it here, before it
    # can leak into a note or a question, not only from the blocking check.
    # ground() also excludes it further down, kept as a second, independent
    # check so ground() stays correct on its own if anything ever calls it
    # without this filter applied first.
    conflicts = [c for c in conflicts if c.section_id != rewritten_id]
    grounded = ground(conflicts, by_id, rewritten_id)
    blocking = [c for c in grounded if c.blocking]

    if not blocking:
        return Decision(action="complete", notes=to_notes(conflicts, grounded, by_id))

    primary_section = blocking[0].section_id
    primary = [c for c in blocking if c.section_id == primary_section]
    deferred = [c for c in conflicts if c not in primary]
    return Decision(
        action="ask", asking=primary, notes=to_notes(deferred, grounded, by_id)
    )

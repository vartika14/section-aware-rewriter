"""DRAFT: write the replacement text for one section.

This is the first AI call, and it's shown the whole document, not just the
target section, so it can match tone and avoid stepping on other sections.
It also decides whether the instruction applies here at all — if not, we
skip DETECT entirely, since there's no draft to check.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from .llm import structured_completion
from .parsing import Section

REWRITE_MARKER = "[REWRITE]"

SYSTEM = """You rewrite one section of a document.

You are given the complete document. Exactly one section is marked [REWRITE].

Rules:
- Return replacement body text for that section only, and never its heading.
- Match the register, tense and formatting conventions of the other sections.
- Do not absorb content that belongs to another section.
- Leave commitments — numbers, dates, quantities, named obligations, boundaries
  — as they are unless the instruction requires changing them.
- Set `applicable` to false, with a one-sentence `inapplicable_reason`, only when
  the instruction genuinely cannot apply to this section — not merely when it is
  vague. When false, leave `new_text` unset rather than inventing something
  adjacent.
- Some instructions hand you the exact words to add — "add a fourth deliverable:
  a change-management plan" — and writing that in is fine, nothing is invented.
- Other instructions ask you to state a specific real fact that nobody has
  given you — "add the name of the account manager," "state the client's
  phone number," "give the exact delivery date" — and that fact does not
  appear anywhere else in the document either. NEVER invent one. Not a
  placeholder, not a plausible-sounding guess. A rewrite that fabricates a
  real fact is worse than one that does nothing at all. Set `applicable` to
  false, and say exactly what's missing.
"""


class DraftResult(BaseModel):
    applicable: bool
    inapplicable_reason: str | None = None
    new_text: str | None = None


def render_document(sections: list[Section], focus_id: str) -> str:
    """Lay the document out for the model, with the target section marked.

    Section ids are included because DETECT refers to sections by id, and the
    model needs to be able to name them.
    """
    return "\n\n".join(
        f"## [{section.id}] {section.heading}"
        f"{' ' + REWRITE_MARKER if section.id == focus_id else ''}\n"
        f"{section.text}"
        for section in sections
    )


def find_section(sections: list[Section], section_id: str) -> Section:
    for section in sections:
        if section.id == section_id:
            return section
    raise KeyError(section_id)


def overlay_texts(sections: list[Section], current_texts: dict[str, str]) -> list[Section]:
    """Swap in the text the author has already accepted for a section, if
    there is any. The id, heading, and position of each section never
    change — only the text.

    Used in two places: when starting a new rewrite (so it can see edits
    already accepted for other sections), and when building the file to
    download (so the file matches what the author actually kept).
    """
    return [
        s.model_copy(update={"text": current_texts[s.id]}) if s.id in current_texts else s
        for s in sections
    ]


def draft_section(
    *,
    sections: list[Section],
    section_id: str,
    instruction: str,
    constraints: Sequence[str] = (),
) -> DraftResult:
    """Rewrite one section.

    `constraints` are extra rules the redraft must follow — e.g. "keep this
    section's fee unchanged" — used on a second draft after the author says
    to hold something. Empty on the first draft.
    """
    section = find_section(sections, section_id)

    user = (
        f"{render_document(sections, section_id)}\n\n"
        f"---\n\n"
        f"Rewrite the section marked {REWRITE_MARKER} ({section.heading}).\n\n"
        f"Instruction: {instruction}"
    )

    if constraints:
        user += "\n\nThe following must hold in your replacement:\n\n" + "\n\n".join(
            constraints
        )

    # Pinned to 0: DETECT's only input is this draft, so a draft that varies
    # makes the interrupt decision vary with it.
    return structured_completion(
        system=SYSTEM, user=user, schema=DraftResult, temperature=0
    )

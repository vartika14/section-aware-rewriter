"""DRAFT: rewrite one section, informed by the whole document.

One model call. Whether the instruction even makes sense for the selected
section is decided here, before anything downstream spends a second call on a
draft nobody asked for.
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


def draft_section(
    *,
    sections: list[Section],
    section_id: str,
    instruction: str,
    constraints: Sequence[str] = (),
) -> DraftResult:
    """Rewrite one section.

    `constraints` carries anything the author has since insisted on — on a
    second draft, that the clause they chose to hold must survive intact. Built
    in Python from a conflict, never asked for, so what the second draft is held
    to can be unit tested. Empty by default, so the first draft's prompt is
    unchanged from before this existed.
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

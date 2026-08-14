"""The rewrite step.

One model call. The whole document goes in as context, so the rewrite is at
least *informed* by the sections it must not contradict — but nothing here
checks whether it actually contradicts them. That is the audit's job, and it is
deliberately a separate call: a model asked to write and critique in one breath
rationalises its own output.
"""

from pydantic import BaseModel

from .llm import structured_completion
from .parsing import Section

REWRITE_MARKER = "[REWRITE]"

SYSTEM = """You rewrite one section of a professional document.

You are given the complete document. Exactly one section is marked [REWRITE].

Rules:
- Return replacement body text for that section only, and never its heading.
- Match the register, tense and formatting conventions of the other sections.
- Do not absorb content that belongs to another section.
- Leave commitments — numbers, dates, quantities, named obligations — as they
  are unless the instruction requires changing them.
- If the instruction cannot be carried out on this section, return the section
  unchanged rather than inventing something adjacent.
"""


class Draft(BaseModel):
    new_text: str


def render_document(sections: list[Section], focus_id: str) -> str:
    """Lay the document out for the model, with the target section marked.

    Section ids are included because every later step — findings, ripple edits —
    refers to sections by id, and the model needs to be able to name them.
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


def draft_rewrite(
    *, sections: list[Section], section_id: str, instruction: str
) -> Draft:
    section = find_section(sections, section_id)

    user = (
        f"{render_document(sections, section_id)}\n\n"
        f"---\n\n"
        f"Rewrite the section marked {REWRITE_MARKER} ({section.heading}).\n\n"
        f"Instruction: {instruction}"
    )

    # Pinned to 0 like the audit, and for the same reason once removed: the
    # audit's only input is this draft, so a draft that varies makes the
    # decision to interrupt vary with it. A consultant who reruns a rewrite and
    # gets a question the second time has learned not to trust either answer.
    return structured_completion(
        system=SYSTEM, user=user, schema=Draft, temperature=0
    )

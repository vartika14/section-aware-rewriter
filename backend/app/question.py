"""Wording the question.

The division of labour here is the point. Python decides *that* a question is
asked and *what the branches are*; the model is allowed to make the sentence read
like a colleague wrote it, and nothing else. Its output is checked against the
branches Python produced, and discarded whole if it drifted.

So the graded judgement stays in code that can be tested without a network, and
the consultant still reads prose rather than a mail-merge.
"""

from enum import Enum

from pydantic import BaseModel

from .llm import structured_completion
from .parsing import Section
from .policy import FindingGroup
from .text import normalize

SYSTEM = """You rephrase a clarifying question that an editing tool is about to
put to the author of a document.

You are given a drafted question and a fixed set of lettered options. Rewrite
them so they read as a knowledgeable colleague would say them out loud.

Hard constraints:
- Return exactly the same option keys, in the same order, meaning the same thing.
- Never add, drop, merge or renumber an option.
- Quote at least one clause from the document EXACTLY as the drafted question
  quotes it, punctuation and all. A question that names no specific words is
  useless to the author.
- Refer to a section by the heading it is given here. Never invent a section
  number, and never use an internal identifier like "s5".
- Ask about the consequence, never re-ask the instruction the author already gave.
- No preamble, no apology, no offer to help further. Two sentences at most.
"""

class Branch(str, Enum):
    """What each lettered option actually means.

    The key is what crosses the wire; the name is what `loop.py` switches on.
    Keeping both in one place is the difference between a branch whose meaning is
    checkable and one that lives inside a label string nobody parses.
    """

    HOLD = "a"      # hold the other section; reshape the rewrite to fit it
    FLAG = "b"      # make the rewrite; flag the other section for review
    ACCEPT = "c"    # make the rewrite; leave the other section as it stands


# The three ways out of "this rewrite invalidates something elsewhere". They are
# exhaustive by construction: either the other section wins, or the rewrite wins
# and the other section is flagged, or the rewrite wins and the mismatch is
# accepted. Anything a consultant might actually choose collapses into one of
# these, which is why they can be generated rather than reasoned about.
BRANCHES = [
    (Branch.HOLD, "Hold {heading} as written, and shape the rewrite to fit it"),
    (Branch.FLAG, "Make the rewrite, and flag {heading} for review"),
    (Branch.ACCEPT, "Make the rewrite, and leave {heading} as it stands"),
]


class Option(BaseModel):
    key: str
    label: str


class Question(BaseModel):
    text: str
    options: list[Option]


def build_options(group: FindingGroup) -> list[Option]:
    """The branches, derived from the group with no model involved."""
    return [
        Option(key=branch.value, label=template.format(heading=group.heading))
        for branch, template in BRANCHES
    ]


def template_text(group: FindingGroup) -> str:
    """The question as Python alone would put it: correct, complete, a bit stiff.

    This is also the fallback, so it has to stand on its own — it names the
    section, quotes the exact clause, and gives the consequence for each finding.
    """
    clauses = " ".join(
        f'It says "{finding.quote}". {finding.explanation}'
        for finding in group.findings
    )
    return (
        f"This rewrite affects {group.heading}. {clauses} "
        f"Only you can settle this. How should I proceed?"
    )


def _kept_the_branches(polished: Question, options: list[Option]) -> bool:
    return [option.key for option in polished.options] == [
        option.key for option in options
    ]


def _kept_a_quote(polished: Question, group: FindingGroup) -> bool:
    """At least one clause must survive the rewording verbatim.

    Quoting the exact words is what separates a question a consultant can act on
    from "this may affect pricing, continue?". The model is free to choose which
    finding to lead with, but not to drop the evidence entirely.
    """
    text = normalize(polished.text)
    return any(normalize(finding.quote) in text for finding in group.findings)


def compose_question(
    group: FindingGroup,
    *,
    sections: list[Section],
    instruction: str,
    polish: bool = True,
) -> Question:
    """Build the question for one group of findings.

    `polish=False` skips the model entirely — used by tests, and the honest
    behaviour if the phrasing call ever needs to be switched off.
    """
    options = build_options(group)
    deterministic = Question(text=template_text(group), options=options)

    if not polish:
        return deterministic

    conflicting = next((s for s in sections if s.id == group.section_id), None)
    user = (
        f"The author asked for this rewrite: {instruction}\n\n"
        f"It has a consequence for {group.heading}, which currently reads:\n\n"
        f"{conflicting.text if conflicting else ''}\n\n"
        f"---\n\nDrafted question: {deterministic.text}\n\n"
        + "\n".join(f"({o.key}) {o.label}" for o in options)
    )

    try:
        polished = structured_completion(
            system=SYSTEM, user=user, schema=Question, temperature=0
        )
    except Exception:  # noqa: BLE001
        # Phrasing is a nicety; the question is not. Any failure here falls back
        # rather than costing the user the clarification altogether.
        return deterministic

    if (
        not polished.text.strip()
        or not _kept_the_branches(polished, options)
        or not _kept_a_quote(polished, group)
    ):
        return deterministic
    return polished

"""Turning `decide()`'s findings into a question the author can answer.

No AI call here — just Python. Each blocking section gets three fixed
options: hold that section and reshape the rewrite (Hold), keep the rewrite
and flag the section for review (Flag), or keep the rewrite and accept the
mismatch (Accept). The author answers each section's row independently.
"""

from enum import Enum

from pydantic import BaseModel

from .conflicts import Conflict, ConflictGroup


class Branch(str, Enum):
    """The three answers. The value is what the frontend sends back; the
    name is what `orchestrator.py` checks against."""

    HOLD = "a"      # hold the other section; reshape the rewrite to fit it
    FLAG = "b"      # make the rewrite; flag the other section for review
    ACCEPT = "c"    # make the rewrite; leave the other section as it stands


BRANCHES = [
    (Branch.HOLD, "Hold {heading} as written, and shape the rewrite to fit it"),
    (Branch.FLAG, "Make the rewrite, and flag {heading} for review"),
    (Branch.ACCEPT, "Make the rewrite, and leave {heading} as it stands"),
]


class Option(BaseModel):
    key: str
    label: str


class QuestionGroup(BaseModel):
    """One row of the question: one section at stake, its conflicts, and the
    three ways to answer for it."""

    section_id: str
    heading: str
    conflicts: list[Conflict]
    options: list[Option]


class Question(BaseModel):
    groups: list[QuestionGroup]


def build_options(conflicts: list[Conflict], *, heading: str) -> list[Option]:
    """The three branches for one section, derived from its heading — no
    model involved."""
    return [
        Option(key=branch.value, label=template.format(heading=heading))
        for branch, template in BRANCHES
    ]


def build_question(groups: list[ConflictGroup]) -> Question:
    """Turn `decide()`'s grouped findings into the question the author sees:
    one row per section that's actually blocking, each with its own answer."""
    return Question(
        groups=[
            QuestionGroup(
                section_id=group.section_id,
                heading=group.heading,
                conflicts=group.conflicts,
                options=build_options(group.conflicts, heading=group.heading),
            )
            for group in groups
        ]
    )

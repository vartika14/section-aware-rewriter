# Simplified Agent Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the seven-concept interrupt policy (`policy.py` + `loop.py`, 520 lines) with a
two-concept one — a grounded quote and the model's own `blocking` judgment — and prove the whole
pipeline generalizes across three structurally different documents, not one.

**Architecture:** Two model calls per rewrite in the common case (DRAFT, DETECT), a third only when
the user picks the branch that needs new text, decided by ~15 lines of pure Python. The user is asked
a clarifying question **at most once, ever** — enforced by the return type of `resume()`, not by a
counter. Full detail in the spec.

**Tech Stack:** Unchanged — Python 3.12, FastAPI, Pydantic v2, pytest, `openai` SDK (Azure), Next.js
15, TypeScript, Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-17-simplified-agent-design.md` — this plan implements every
numbered section. `docs/superpowers/specs/2026-08-13-section-rewrite-agent-design.md` (superseded)
is kept for the measured findings §0 of the new spec draws from.

## Global Constraints

- **Python 3.12+**, `backend/.venv/bin/python`. No new dependencies — `requirements.txt` is final.
- **Offline by default.** Every test outside `test_calibration.py` substitutes the model at
  `app.llm.structured_completion` via `monkeypatch.setattr("app.<module>.structured_completion", ...)`.
- **No domain-specific vocabulary anywhere in code or prompts** — no money/date/fee keyword lists.
  This is the direct fix for the old design's one non-generalizing piece (spec §0, §6) and it is a
  constraint on every task that touches a prompt, not just the sample documents.
- **Findings/conflicts in tests are hand-built, including dishonest ones** — never recorded from a
  live call.
- **Ask the user a clarifying question at most once per rewrite.** No task may add a counter, a cap,
  or a suppression list to enforce this — it must be true because `resume()`'s return type cannot
  express asking again (spec §2.1, §4.5).
- **Never silently resolve a conflict without asking.** Every conflict is either blocking (asks) or a
  note (reported, never applied outside the selected section).
- **Docstrings explain *why*.** Match the register already in `llm.py`/`config.py`/`text.py`, which
  are unchanged and are the house style.
- **Commit after every task.** Message body explains the reasoning. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```
- **Delete superseded files in the same task that replaces them.** The tree should never hold two
  competing implementations of the same responsibility, and the suite must stay green after every task.

---

## File Structure

**Deleted, one per the task that replaces it:** `app/agent.py`, `app/audit.py`, `app/policy.py`,
`app/loop.py`, `tests/test_agent.py`, `tests/test_audit.py`, `tests/test_policy.py`, `tests/test_loop.py`.

**Unchanged:** `app/config.py`, `app/llm.py`, `app/text.py`, `app/store.py` (revised, not replaced),
`app/main.py` (revised), `scripts/smoke_test.py`.

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/rewrite.py` | DRAFT. `render_document()`, `find_section()` (moved from `agent.py`), `draft_section()` — gains `applicable`/`inapplicable_reason` on its own result. |
| `backend/app/conflicts.py` | DETECT + the whole interrupt policy: `Conflict`, `Note`, `Decision` models; `find_conflicts()` (dynamic per-request schema); `ground()`; `decide()`. |
| `backend/app/question.py` | Revised in place: same Python-builds-branches/model-only-phrases pattern, retyped from `FindingGroup` to `list[Conflict]`. |
| `backend/app/orchestrator.py` | The whole state machine: `start()`, `resume()`, `Outcome` types, exceptions. Replaces `loop.py`. |
| `backend/tests/test_rewrite.py` | Replaces `test_agent.py`. |
| `backend/tests/test_conflicts.py` | Replaces `test_audit.py` + `test_policy.py`. This is the file most worth reading in the session — it is the new interrupt policy's test suite. |
| `backend/tests/test_orchestrator.py` | Replaces `test_loop.py`. |
| `backend/scripts/make_policy_docx.py` | Second sample document — an internal policy, no money vocabulary. |
| `backend/scripts/make_charter_docx.py` | Third sample document — a project charter, a different domain again. |

**Frontend, revised in place:** `lib/api.ts`, `app/components/ResultPanel.tsx`; `app/page.tsx` checked
for fallout, not expected to need logic changes.

---

## Task 1: `parsing.py` — the preamble stops shifting the numbering

**Files:**
- Modify: `backend/app/parsing.py:54-60` (`parse_docx`)
- Modify: `backend/tests/test_parsing.py:79-93` (`test_text_before_the_first_heading_is_not_lost`)

**Interfaces:**
- Produces: unchanged `Section`/`ParsedDocument` shape. The only change is which id a preamble gets.
  Every other module that reads `Section.id` is unaffected — `"preamble"` is just another string id.

- [ ] **Step 1: Update the existing test**

Replace `test_text_before_the_first_heading_is_not_lost` in `backend/tests/test_parsing.py`:

```python
def test_text_before_the_first_heading_gets_a_fixed_id_not_a_shifted_one():
    """A proposal often opens with a title block or a paragraph of preamble.
    Dropping it would silently hide part of the document from the agent — but
    giving it `s1` used to shift every real section's number by one, which
    silently misaimed three calibration tests in the old design."""
    data = make_docx(
        [
            ("Normal", "Prepared for Meridian Retail BV, 13 August 2026."),
            ("Heading 1", "1. Executive Summary"),
            ("Normal", "Body."),
        ]
    )

    parsed = parse_docx(data)

    assert "Prepared for Meridian Retail BV" in parsed.sections[0].text
    assert parsed.sections[0].id == "preamble"
    assert parsed.sections[1].id == "s1"
    assert len(parsed.sections) == 2
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_parsing.py -q
```

Expected: `AssertionError` — the current code assigns `s1` to the preamble.

- [ ] **Step 3: Fix `parse_docx`**

Replace the `sections=[...]` block in `backend/app/parsing.py` (currently lines 54-60):

```python
    sections: list[Section] = []
    n = 1
    for heading, text in pairs:
        if heading == PREAMBLE_HEADING:
            # A fixed id, outside the numbering sequence — so it never shifts
            # what a real section's number means. Only ever produced by the
            # heading-styled path; the blank-line fallback has no preamble
            # concept, since each block's own first line is its heading.
            sections.append(Section(id="preamble", heading=heading, text=text))
        else:
            sections.append(Section(id=f"s{n}", heading=heading, text=text))
            n += 1

    return ParsedDocument(sections=sections, headings_detected=headings_detected)
```

- [ ] **Step 4: Run the suite**

```bash
./.venv/bin/python -m pytest tests/test_parsing.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/parsing.py backend/tests/test_parsing.py
git commit -m "$(cat <<'EOF'
Stop the preamble from shifting every section's number

A document that opens with a bare title line took s1 for that preamble and
pushed every real section one number further than its own heading suggested —
2. Scope of Work was s3. It silently misaimed three calibration tests once.

The preamble now gets a fixed id, "preamble", outside the s{n} sequence. Numbered
sections start at s1 regardless of whether a preamble exists.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `rewrite.py` — DRAFT, with applicability decided here

**Files:**
- Create: `backend/app/rewrite.py`
- Create: `backend/tests/test_rewrite.py`
- Delete: `backend/app/agent.py`, `backend/tests/test_agent.py`

**Interfaces:**
- Produces:
  ```python
  REWRITE_MARKER = "[REWRITE]"
  def render_document(sections: list[Section], focus_id: str) -> str
  def find_section(sections: list[Section], section_id: str) -> Section   # raises KeyError
  class DraftResult(BaseModel):
      applicable: bool
      inapplicable_reason: str | None = None
      new_text: str | None = None
  def draft_section(*, sections: list[Section], section_id: str, instruction: str,
                     constraints: Sequence[str] = ()) -> DraftResult
  ```
  Task 7 (`orchestrator.start`) checks `applicable` before spending a DETECT call. Task 4
  (`orchestrator.resume`, branch HOLD) passes `constraints`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_rewrite.py` — `render_document`/`find_section` tests are `test_agent.py`'s
existing four, moved verbatim (they test behavior that isn't changing); the constraint tests are also
moved verbatim; new tests cover `applicable`:

```python
"""Tests for DRAFT: the context assembly and the rewrite call itself.

The model call is substituted at `app.rewrite.structured_completion`. Whether the
instruction is applicable to the section is decided HERE, before a conflict
check is ever run — a nonsensical instruction should never cost a DETECT call.
"""

import pytest

from app.parsing import Section
from app.rewrite import DraftResult, draft_section, find_section, render_document

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="Act on it this quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000."),
]


def test_rendered_context_includes_every_section():
    rendered = render_document(SECTIONS, focus_id="s2")
    for section in SECTIONS:
        assert section.heading in rendered
        assert section.text in rendered


def test_rendered_context_marks_the_section_being_rewritten():
    rendered = render_document(SECTIONS, focus_id="s2")
    focus_line = next(l for l in rendered.splitlines() if "2. Scope of Work" in l)
    other_line = next(l for l in rendered.splitlines() if "3. Fees" in l)
    assert "REWRITE" in focus_line
    assert "REWRITE" not in other_line


def test_draft_section_returns_the_models_new_text(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        return schema(applicable=True, new_text="Named deliverables: a map.")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    result = draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert isinstance(result, DraftResult)
    assert result.applicable is True
    assert result.new_text == "Named deliverables: a map."


def test_draft_section_sends_the_whole_document(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["user"] = user
        return schema(applicable=True, new_text="...")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert "EUR 48,000" in captured["user"]
    assert "Act on it this quarter." in captured["user"]
    assert "Be concrete." in captured["user"]


def test_draft_section_is_pinned_to_temperature_zero(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["temperature"] = kwargs.get("temperature")
        return schema(applicable=True, new_text="...")

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Be concrete.")

    assert captured["temperature"] == 0


def test_draft_section_rejects_an_unknown_section_id():
    with pytest.raises(KeyError):
        draft_section(sections=SECTIONS, section_id="nope", instruction="Be concrete.")


def test_an_inapplicable_instruction_carries_no_new_text(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        return schema(
            applicable=False,
            inapplicable_reason="This section sets no dates to bring forward.",
            new_text=None,
        )

    monkeypatch.setattr("app.rewrite.structured_completion", fake)

    result = draft_section(sections=SECTIONS, section_id="s2", instruction="Bring the date forward.")

    assert result.applicable is False
    assert result.new_text is None
    assert "dates" in result.inapplicable_reason


def test_a_constraint_reaches_the_model(monkeypatch):
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(applicable=True, new_text="trimmed")

    monkeypatch.setattr("app.rewrite.structured_completion", capture)

    draft_section(
        sections=SECTIONS, section_id="s2", instruction="Make this concrete.",
        constraints=["3. Fees must stand exactly as written."],
    )

    assert "3. Fees must stand exactly as written." in seen["user"]


def test_no_constraints_leaves_the_prompt_as_it_was(monkeypatch):
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(applicable=True, new_text="drafted")

    monkeypatch.setattr("app.rewrite.structured_completion", capture)

    draft_section(sections=SECTIONS, section_id="s2", instruction="Make this concrete.")

    assert "must hold" not in seen["user"]
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.rewrite'`.

- [ ] **Step 3: Create `rewrite.py`**

```python
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
```

- [ ] **Step 4: Run, then remove the old module**

```bash
./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

Expected: all pass. Then:

```bash
rm backend/app/agent.py backend/tests/test_agent.py
grep -rln "app.agent\|app\.agent\|from \.agent\|from app import agent" backend/app backend/tests
```

The grep must return nothing before the next step — if it returns a file, fix that reference now
rather than carrying a dangling import forward.

- [ ] **Step 5: Run the whole suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: passes, minus whatever still imports the now-deleted `audit`/`policy`/`loop`/`question`
modules (those are fixed in later tasks — if `main.py` fails to import, that's expected until Task 9).

- [ ] **Step 6: Commit**

```bash
git add backend/app/rewrite.py backend/tests/test_rewrite.py
git rm backend/app/agent.py backend/tests/test_agent.py
git commit -m "$(cat <<'EOF'
Replace agent.py with rewrite.py — applicability decided at DRAFT

The old design ran a full audit call before checking whether the instruction
even applied to the section. DraftResult now carries applicable/inapplicable_reason
directly, so a nonsensical instruction is caught before a second model call is
spent on it — the decline path gets cheaper, not just simpler.

render_document() and find_section() move here unchanged; everything else in
this file is the same rewrite call as before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `conflicts.py` — models and DETECT

**Files:**
- Create: `backend/app/conflicts.py` (this task: models + `find_conflicts`)
- Create: `backend/tests/test_conflicts.py` (this task: DETECT section only)

**Interfaces:**
- Produces:
  ```python
  class Conflict(BaseModel):
      section_id: str
      quote: str
      explanation: str
      blocking: bool

  class Note(BaseModel):
      section_id: str
      heading: str
      quote: str
      explanation: str
      verified: bool

  def find_conflicts(*, sections: list[Section], section_id: str, instruction: str,
                      new_text: str) -> list[Conflict]
  ```
  Task 4 adds `ground()`/`decide()`/`Decision` to this same file. `find_section` comes from `rewrite.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_conflicts.py`:

```python
"""Tests for DETECT and the interrupt policy — conflicts.py in full.

Split into three parts as the file grows across this task and the next:
DETECT (this task, the one LLM call, tested with the seam substituted),
ground() and decide() (pure Python, hand-built findings including dishonest
ones — this is the new interrupt policy's test suite, the direct replacement
for the old test_policy.py).
"""

from app.parsing import Section
from app.conflicts import Conflict, find_conflicts

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000 covers the scope in section 2."),
]


# --- DETECT ----------------------------------------------------------------


def test_find_conflicts_returns_the_models_structured_findings(monkeypatch):
    def fake(*, system, user, schema, **kwargs):
        return schema(
            findings=[
                Conflict(
                    section_id="s3",
                    quote="A fixed fee of EUR 48,000",
                    explanation="Priced against the old scope.",
                    blocking=True,
                )
            ]
        )

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    conflicts = find_conflicts(
        sections=SECTIONS, section_id="s2", instruction="Be concrete.", new_text="new text"
    )

    assert conflicts == [
        Conflict(
            section_id="s3", quote="A fixed fee of EUR 48,000",
            explanation="Priced against the old scope.", blocking=True,
        )
    ]


def test_find_conflicts_sends_old_and_new_text_and_the_rest_of_the_document(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["user"] = user
        return schema(findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    find_conflicts(
        sections=SECTIONS, section_id="s2", instruction="Name the deliverables.",
        new_text="Three deliverables, concretely named.",
    )

    assert "EUR 48,000" in captured["user"]           # the rest of the document
    assert "Three deliverables, concretely named." in captured["user"]  # the proposed text
    assert "Name the deliverables." in captured["user"]


def test_find_conflicts_is_pinned_to_temperature_zero(monkeypatch):
    captured = {}

    def fake(*, system, user, schema, **kwargs):
        captured["temperature"] = kwargs.get("temperature")
        return schema(findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", fake)

    find_conflicts(sections=SECTIONS, section_id="s2", instruction="x", new_text="y")

    assert captured["temperature"] == 0


def test_the_section_id_field_is_constrained_to_real_ids():
    """The dynamic schema is the whole fix for the old id-repair machinery: the
    model literally cannot return an id that doesn't exist in this document."""
    from pydantic import ValidationError

    from app.conflicts import _conflict_schema

    schema = _conflict_schema(["s1", "s2", "s3"])

    schema(findings=[{"section_id": "s3", "quote": "x", "explanation": "x", "blocking": True}])

    with pytest.raises(ValidationError):
        schema(findings=[{"section_id": "s99", "quote": "x", "explanation": "x", "blocking": True}])
```

`import pytest` at the top of the file, alongside the existing imports, is required for this test.

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_conflicts.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.conflicts'`.

- [ ] **Step 3: Create `conflicts.py` — models and `find_conflicts` only**

```python
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
```

- [ ] **Step 4: Run the DETECT tests**

```bash
./.venv/bin/python -m pytest tests/test_conflicts.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/conflicts.py backend/tests/test_conflicts.py
git commit -m "$(cat <<'EOF'
Add conflicts.py: DETECT, with ids enforced by the schema

Same separate-call framing as the old audit.py — anonymous review, no hint the
model is reading its own draft. The difference is what happens to the id it
returns: the response schema is built per request with section_id constrained
to a Literal over this document's real ids, so an invented id fails schema
validation and goes through the existing retry, instead of reaching a three-
strategy repair function after the fact.

blocking is the model's own judgment, trusted directly rather than layered under
a kind taxonomy and a keyword regex — the room "extra LLM calls for conflict
detection" bought. Python's only say is the grounding check in the next commit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `conflicts.py` — `ground()` and `decide()`

**Files:**
- Modify: `backend/app/conflicts.py` (append)
- Modify: `backend/tests/test_conflicts.py` (append)
- Delete: `backend/app/audit.py`, `backend/app/policy.py`, `backend/tests/test_audit.py`, `backend/tests/test_policy.py`

**Interfaces:**
- Produces:
  ```python
  def ground(conflicts: list[Conflict], sections_by_id: dict[str, Section],
             rewritten_id: str) -> list[Conflict]
  def to_notes(conflicts: list[Conflict], grounded: list[Conflict],
               sections_by_id: dict[str, Section]) -> list[Note]
  class Decision(BaseModel):
      action: Literal["ask", "complete"]
      asking: list[Conflict] = []
      notes: list[Note] = []
  def decide(conflicts: list[Conflict], sections: list[Section],
              rewritten_id: str) -> Decision
  ```
  Task 5 (`question.py`) consumes `Decision.asking`. Tasks 7–8 (`orchestrator.py`) consume `decide`,
  `ground`, `to_notes` directly.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_conflicts.py`:

```python
# --- ground(): is the conflict real, and is it actually another section? ---


BY_ID = {s.id: s for s in SECTIONS}


def conflict(**overrides) -> Conflict:
    """A real, blocking conflict against s3 — the shape that should ask."""
    return Conflict(
        **{
            "section_id": "s3",
            "quote": "A fixed fee of EUR 48,000",
            "explanation": "Priced against the old scope.",
            "blocking": True,
            **overrides,
        }
    )


def test_a_quote_lifted_from_the_section_is_grounded():
    assert ground([conflict()], BY_ID, rewritten_id="s2") == [conflict()]


def test_a_quote_that_appears_nowhere_is_dropped():
    assert ground([conflict(quote="a fixed fee of EUR 90,000")], BY_ID, rewritten_id="s2") == []


def test_whitespace_and_case_do_not_defeat_grounding():
    assert ground(
        [conflict(quote="a  FIXED   fee\nof EUR 48,000")], BY_ID, rewritten_id="s2"
    ) == [conflict(quote="a  FIXED   fee\nof EUR 48,000")]


def test_a_conflict_naming_an_unknown_section_is_dropped():
    assert ground([conflict(section_id="s99")], BY_ID, rewritten_id="s2") == []


def test_a_conflict_against_the_rewritten_section_itself_is_dropped():
    """A section cannot conflict with itself — that is just the rewrite. This is
    the direct fix for the old self-reference hole: it cannot be reached here,
    because there is no separate 'resolution' citation left to ground."""
    assert ground([conflict(section_id="s2")], BY_ID, rewritten_id="s2") == []


# --- decide(): the whole interrupt policy -----------------------------------


def test_no_conflicts_completes_silently():
    """The true negative. Precision matters as much as recall."""
    decision = decide([], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert decision.notes == []


def test_a_non_blocking_conflict_completes_as_a_note():
    decision = decide([conflict(blocking=False)], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert [n.section_id for n in decision.notes] == ["s3"]


def test_an_unverified_conflict_never_blocks_but_is_still_reported():
    """A possibly hallucinated conflict must not interrupt anyone — but hiding
    it silently is the class of bug this tool exists to prevent."""
    decision = decide([conflict(quote="not in the document")], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
    assert decision.notes[0].verified is False


def test_a_blocking_grounded_conflict_asks():
    decision = decide([conflict()], SECTIONS, rewritten_id="s2")
    assert decision.action == "ask"
    assert [c.section_id for c in decision.asking] == ["s3"]


def test_conflicts_against_the_same_section_are_all_asked_about_together():
    decision = decide(
        [conflict(), conflict(quote="covers the scope in section 2", explanation="also fee-related")],
        SECTIONS, rewritten_id="s2",
    )
    assert decision.action == "ask"
    assert len(decision.asking) == 2


def test_only_the_first_blocking_section_is_asked_about_the_rest_become_notes():
    """Two blocking conflicts, two different sections: one question, ever — the
    other becomes a note rather than a second interrupt."""
    decision = decide(
        [
            conflict(section_id="s3"),
            conflict(section_id="s1", quote="A recommendation within the quarter"),
        ],
        SECTIONS, rewritten_id="s2",
    )
    assert decision.action == "ask"
    assert {c.section_id for c in decision.asking} == {"s3"}
    assert "s1" in [n.section_id for n in decision.notes]


def test_a_conflict_against_the_rewritten_section_never_blocks():
    decision = decide([conflict(section_id="s2")], SECTIONS, rewritten_id="s2")
    assert decision.action == "complete"
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_conflicts.py -q
```

Expected: `ImportError: cannot import name 'ground'`.

- [ ] **Step 3: Append `ground`, `to_notes`, `Decision`, `decide`**

```python
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
```

- [ ] **Step 4: Run the conflicts tests, then remove the superseded modules**

```bash
./.venv/bin/python -m pytest tests/test_conflicts.py -q
```

Expected: all pass. Then:

```bash
rm backend/app/audit.py backend/app/policy.py backend/tests/test_audit.py backend/tests/test_policy.py
grep -rln "app\.audit\|app\.policy\|from \.audit\|from \.policy" backend/app backend/tests
```

Must return nothing.

- [ ] **Step 5: Run the whole suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: passes except anything still importing `question`'s old `FindingGroup`-typed API,
`loop.py`, or `main.py`'s old imports — fixed in Tasks 5, 7–9.

- [ ] **Step 6: Commit**

```bash
git add backend/app/conflicts.py backend/tests/test_conflicts.py
git rm backend/app/audit.py backend/app/policy.py backend/tests/test_audit.py backend/tests/test_policy.py
git commit -m "$(cat <<'EOF'
Add ground() and decide() — the whole interrupt policy, in ~40 lines

Replaces audit.py + policy.py (391 lines combined) with two functions and a
sixteen-test suite. The old design's seven interacting concepts behind "should
this ask" — kind, quotes_a_commitment, is_verified, is_resolvable, the deriving-
quote self-reference guard, asked_section_ids, flagged-vs-ripples — are down to
two: is the quote grounded, and does the model say it's blocking.

The self-reference guard disappears rather than gets ported: ground() excludes
the section being rewritten from the candidate pool before anything is decided,
so there is no separate "resolution" citation left to fail closed on.

decide() only ever asks about the first blocking section found. Everything else
this round becomes a note. That is the entire mechanism behind "at most one
question, ever" — there is nothing to cap, because there is only ever one group.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `question.py` — retyped from `FindingGroup` to `list[Conflict]`

**Files:**
- Modify: `backend/app/question.py` (in place — the Python-builds/model-phrases pattern is unchanged, only the input type changes)
- Modify: `backend/tests/test_question.py` (in place)

**Interfaces:**
- Consumes: `Conflict` from `conflicts.py`.
- Produces: unchanged externally —
  ```python
  class Branch(str, Enum): HOLD = "a"; FLAG = "b"; ACCEPT = "c"
  class Option(BaseModel): key: str; label: str
  class Question(BaseModel): text: str; options: list[Option]
  def build_options(conflicts: list[Conflict], *, heading: str) -> list[Option]
  def compose_question(conflicts: list[Conflict], *, heading: str, sections: list[Section],
                        instruction: str, polish: bool = True) -> Question
  ```
  Task 8 (`orchestrator.resume`) and Task 7 (`orchestrator.start`) call `compose_question` with
  `decision.asking` and the heading looked up from `decision.asking[0].section_id`.

- [ ] **Step 1: Read the current file, then rewrite it**

The `Branch` enum, `BRANCHES`, `Option`, `Question` classes are unchanged from the current
`question.py` (written in the prior session's phase-4 work) — copy them as-is. What changes:
`build_options` and `template_text` take `conflicts: list[Conflict]` plus an explicit `heading: str`
instead of a `FindingGroup`; `compose_question` takes the same two parameters instead of one `group`.

Read `backend/app/question.py` in full before editing, to carry the `SYSTEM` prompt and the
verify-or-fallback logic (`_kept_the_branches`, `_kept_a_quote`) forward unchanged — only the type
signatures and the two functions that build from a group need to change.

- [ ] **Step 2: Update the tests first**

Rewrite `backend/tests/test_question.py`'s fixtures — replace the `group()` helper:

```python
def conflicts(*items: Conflict) -> list[Conflict]:
    return list(items) or [
        Conflict(
            section_id="s4", quote="A fixed fee of EUR 48,000",
            explanation="The fee was priced against the old, vaguer scope.",
            blocking=True,
        )
    ]

HEADING = "4. Fees and Payment"
```

Every call site in the file that did `compose_question(group(), sections=..., instruction=...)`
becomes `compose_question(conflicts(), heading=HEADING, sections=..., instruction=...)`; every
`build_options(group())` becomes `build_options(conflicts(), heading=HEADING)`. The assertions
themselves (branch keys, quote survival, instruction reaching the prompt, the `Branch` enum tests
from the prior session, the polish/fallback tests) are unchanged — only the construction changes.

- [ ] **Step 3: Run to verify it fails, then update `question.py`, then run again**

```bash
./.venv/bin/python -m pytest tests/test_question.py -q   # fails: TypeError on the new call shape
```

Edit `backend/app/question.py`: change the `from .policy import FindingGroup` import to
`from .conflicts import Conflict`; change `build_options(group: FindingGroup)` to
`build_options(conflicts: list[Conflict], *, heading: str)`, replacing `group.heading` with `heading`
and `group.findings` with `conflicts` throughout that function and `template_text`; change
`compose_question`'s signature from `(group: FindingGroup, *, sections, instruction, polish=True)` to
`(conflicts: list[Conflict], *, heading: str, sections, instruction, polish=True)`, and replace every
`group.section_id`/`group.heading`/`group.findings` reference in its body accordingly (the
`conflicting = next((s for s in sections if s.id == group.section_id), None)` line becomes
`next((s for s in sections if s.id == conflicts[0].section_id), None)`).

```bash
./.venv/bin/python -m pytest tests/test_question.py -q
```

Expected: all pass.

- [ ] **Step 4: Run the whole suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: everything except `main.py`'s imports (Task 9) and anything still touching `loop.py`
(Tasks 6–8) passes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/question.py backend/tests/test_question.py
git commit -m "$(cat <<'EOF'
Retype question.py from FindingGroup to list[Conflict]

The Python-builds-the-branches, model-only-phrases split is unchanged — this is
a type migration, not a redesign. FindingGroup no longer exists now that decide()
only ever produces one group to ask about; the heading it carried is passed
explicitly instead.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `store.py` — the simplified session

**Files:**
- Modify: `backend/app/store.py`

**Interfaces:**
- Produces:
  ```python
  class RewriteSession(BaseModel):
      document_id: str
      section_id: str
      instruction: str
      draft_text: str
      asking: list[Conflict]
      notes: list[Note]
      resolved: bool = False
  def save_document(parsed: ParsedDocument) -> str
  def get_document(document_id: str) -> ParsedDocument | None
  def save_session(session: RewriteSession) -> str
  def get_session(session_id: str) -> RewriteSession | None
  ```
  Six fields, down from nine (`groups`, `ripples`, `answers`, `asked_section_ids`, `completed` become
  `asking`, `notes`, `resolved`). Task 7 populates it; Task 8 reads and mutates it.

No new tests — `store.py` has never had its own test file; it is exercised through
`test_orchestrator.py` and `test_api.py`, matching the prior convention.

- [ ] **Step 1: Rewrite the session class**

Replace the `RewriteSession` class and its imports in `backend/app/store.py`:

```python
from .conflicts import Conflict, Note

...

class RewriteSession(BaseModel):
    """A rewrite that stopped to ask one question, and everything needed to
    finish it.

    `draft_text` lets the answer resume from the rewrite that already exists
    rather than re-running DRAFT blind. `asking` is the group the pending
    question is about. `notes` are consequences already decided not to ask
    about — kept here so `resume()`'s branches that don't call the model again
    can still return them with the final result.

    `resolved` makes a finished session terminal: a stale tab answering twice
    gets a 409, not a second run of the loop. There is no round counter and no
    per-section suppression list, because there is only ever one round.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    asking: list[Conflict]
    notes: list[Note]
    resolved: bool = False
```

`save_document`/`get_document`/`save_session`/`get_session` and the two module-level dicts are
unchanged.

- [ ] **Step 2: Confirm it at least imports** (the full suite won't pass yet — `main.py` and `loop.py`
  still reference the old shape)

```bash
./.venv/bin/python -c "import app.store"
```

Expected: clean import.

- [ ] **Step 3: Commit**

```bash
git add backend/app/store.py
git commit -m "$(cat <<'EOF'
Simplify RewriteSession to six fields

groups/ripples/answers/asked_section_ids/completed collapse to asking/notes/
resolved. Nothing here manages a second round, because there is no second round.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `orchestrator.py` — `start()`

**Files:**
- Create: `backend/app/orchestrator.py` (this task: `start()` and the outcome types)
- Create: `backend/tests/test_orchestrator.py` (this task: `start()` only)
- Delete: nothing yet — `loop.py` is removed once `resume()` also exists (Task 8), so `main.py` has a
  working import to fall back to for exactly one task.

**Interfaces:**
- Produces:
  ```python
  class UnknownDocument(LookupError): ...
  class UnknownSection(LookupError): ...
  class UnknownSession(LookupError): ...
  class SessionFinished(RuntimeError): ...
  class Completed(BaseModel):
      section_id: str; old_text: str; new_text: str; notes: list[Note] = []
  class Asking(BaseModel):
      session_id: str; section_id: str; question: Question
  class Declined(BaseModel):
      section_id: str; reason: str
  Outcome = Completed | Asking | Declined
  def start(document_id: str, *, section_id: str, instruction: str) -> Outcome
  ```
  Note: **`Completed` has no `assumptions` field** — there is nothing left for the cap to state an
  assumption about, since there is no cap. Task 9 (`main.py`) maps this directly.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_orchestrator.py`:

```python
"""Tests for the suspendable run.

start() may return Asking; resume() (added next task) may not — its return type
is Completed | Declined, which is what makes "at most one question, ever" a fact
about the type checker rather than a fact you have to trust a counter for.
"""

import pytest

from app import orchestrator, store
from app.conflicts import Conflict
from app.parsing import ParsedDocument, Section

SECTIONS = [
    Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
    Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
    Section(id="s4", heading="4. Fees and Payment", text="A fixed fee of EUR 48,000 covers it."),
]


@pytest.fixture
def document_id() -> str:
    return store.save_document(ParsedDocument(sections=SECTIONS, headings_detected=True))


@pytest.fixture
def model(monkeypatch):
    """Substitute DRAFT and DETECT; fail the phrasing call on purpose — this
    file asserts on the loop, not on wording."""
    state = {"applicable": True, "new_text": "drafted", "conflicts": []}

    def draft(**kwargs):
        return kwargs["schema"](
            applicable=state["applicable"],
            new_text=state["new_text"] if state["applicable"] else None,
            inapplicable_reason=None if state["applicable"] else "no",
        )

    def detect(**kwargs):
        return kwargs["schema"](
            findings=[c.model_dump() for c in state["conflicts"]]
        )

    monkeypatch.setattr("app.rewrite.structured_completion", draft)
    monkeypatch.setattr("app.conflicts.structured_completion", detect)
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return state


def test_no_conflicts_completes(document_id, model):
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Completed)
    assert outcome.new_text == "drafted"
    assert outcome.notes == []


def test_a_blocking_conflict_suspends(document_id, model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 48,000",
                 explanation="Priced against the old scope.", blocking=True)
    ]
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Asking)
    assert store.get_session(outcome.session_id).section_id == "s2"


def test_an_inapplicable_instruction_declines_before_a_detect_call(document_id, model, monkeypatch):
    model["applicable"] = False
    calls = []
    monkeypatch.setattr(
        "app.conflicts.structured_completion",
        lambda **kw: calls.append(1) or kw["schema"](findings=[]),
    )

    outcome = orchestrator.start(document_id, section_id="s2", instruction="Nonsense here.")

    assert isinstance(outcome, orchestrator.Declined)
    assert calls == []  # DETECT was never called


def test_an_unknown_document_is_not_a_crash(model):
    with pytest.raises(orchestrator.UnknownDocument):
        orchestrator.start("nope", section_id="s1", instruction="x")


def test_an_unknown_section_is_not_a_crash(document_id, model):
    with pytest.raises(orchestrator.UnknownSection):
        orchestrator.start(document_id, section_id="s99", instruction="x")
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.orchestrator'`.

- [ ] **Step 3: Create `orchestrator.py` — outcome types and `start()`**

```python
"""The suspendable run. `start()` may ask one question; `resume()` (next task)
answers it and always finishes — its return type has no `Asking` arm, which is
what makes "at most one question, ever" a property of the type checker.
"""

from pydantic import BaseModel

from . import store
from .conflicts import Note, decide, find_conflicts
from .question import Question, compose_question
from .rewrite import draft_section, find_section


class UnknownDocument(LookupError):
    """Not in the store — never uploaded, or lost to a restart."""


class UnknownSection(LookupError):
    """No section with that id in this document."""


class UnknownSession(LookupError):
    """No suspended rewrite with that id."""


class SessionFinished(RuntimeError):
    """This rewrite already finished. The stale-tab case."""


class Completed(BaseModel):
    section_id: str
    old_text: str
    new_text: str
    notes: list[Note] = []


class Asking(BaseModel):
    session_id: str
    section_id: str
    question: Question


class Declined(BaseModel):
    section_id: str
    reason: str


Outcome = Completed | Asking | Declined


def start(document_id: str, *, section_id: str, instruction: str) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    try:
        section = find_section(document.sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_section(sections=document.sections, section_id=section_id, instruction=instruction)

    if not draft.applicable:
        return Declined(
            section_id=section.id,
            reason=draft.inapplicable_reason or "That instruction does not apply to this section.",
        )

    conflicts = find_conflicts(
        sections=document.sections, section_id=section_id,
        instruction=instruction, new_text=draft.new_text,
    )
    decision = decide(conflicts, document.sections, rewritten_id=section_id)

    if decision.action == "complete":
        return Completed(
            section_id=section.id, old_text=section.text,
            new_text=draft.new_text, notes=decision.notes,
        )

    heading = find_section(document.sections, decision.asking[0].section_id).heading
    question = compose_question(
        decision.asking, heading=heading, sections=document.sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id=section_id, instruction=instruction,
            draft_text=draft.new_text, asking=decision.asking, notes=decision.notes,
        )
    )
    return Asking(session_id=session_id, section_id=section.id, question=question)
```

- [ ] **Step 4: Run**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Add orchestrator.py: start() — decline before a DETECT call is spent

An inapplicable instruction is caught at DRAFT (rewrite.py) and returned as
Declined before find_conflicts() ever runs — the old design ran the full audit
first and declined afterward.

resume() lands in the next commit; loop.py stays in place until then so main.py
has a working import throughout this task.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `orchestrator.py` — `resume()`, and `loop.py` retired

**Files:**
- Modify: `backend/app/orchestrator.py` (append `resume()`)
- Modify: `backend/tests/test_orchestrator.py` (append)
- Delete: `backend/app/loop.py`, `backend/tests/test_loop.py`

**Interfaces:**
- Produces: `def resume(session_id: str, *, option_key: str) -> Completed | Declined` — note the
  narrower return type versus `start()`. `Declined` can only occur here in the sense of the type
  union; in practice `resume` never produces it (there is no re-check of applicability), but the type
  is shared with `Outcome` for Task 9's mapper to stay uniform. Also produces `Branch` re-exported
  from `question.py` for convenience at the call site — no, keep it explicit: `main.py` imports
  `Branch` from `question.py` directly, `orchestrator.py` imports it internally.
  ```python
  def hold_constraint(conflicts: list[Conflict], heading: str) -> str
  ```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_orchestrator.py`:

```python
from app.question import Branch


def asked(document_id: str) -> orchestrator.Asking:
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")
    assert isinstance(outcome, orchestrator.Asking)
    return outcome


@pytest.fixture
def blocking_model(model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 48,000",
                 explanation="Priced against the old scope.", blocking=True)
    ]
    return model


def test_holding_produces_a_second_draft(document_id, blocking_model):
    a = asked(document_id)
    blocking_model["new_text"] = "second draft"
    blocking_model["conflicts"] = []   # the re-check finds nothing new

    outcome = orchestrator.resume(a.session_id, option_key="a")

    assert isinstance(outcome, orchestrator.Completed)
    assert outcome.new_text == "second draft"


def test_holding_reports_what_the_recheck_finds_as_a_note_never_a_second_question(
    document_id, blocking_model
):
    a = asked(document_id)
    blocking_model["conflicts"] = [
        Conflict(section_id="s1", quote="A recommendation within the quarter",
                 explanation="No longer supported by the trimmed scope.", blocking=True)
    ]

    outcome = orchestrator.resume(a.session_id, option_key="a")

    assert isinstance(outcome, orchestrator.Completed)  # never Asking — the type already forbids it
    assert "s1" in [n.section_id for n in outcome.notes]


def test_flagging_returns_the_stored_draft_and_keeps_the_finding_as_a_note(document_id, blocking_model):
    a = asked(document_id)
    outcome = orchestrator.resume(a.session_id, option_key="b")

    assert outcome.new_text == "drafted"   # the FIRST draft, untouched
    assert "s4" in [n.section_id for n in outcome.notes]


def test_flagging_calls_the_model_not_at_all(document_id, blocking_model, monkeypatch):
    a = asked(document_id)
    calls = []
    monkeypatch.setattr("app.rewrite.structured_completion", lambda **kw: calls.append(1))

    orchestrator.resume(a.session_id, option_key="b")

    assert calls == []


def test_accepting_returns_the_stored_draft_and_drops_the_finding(document_id, blocking_model):
    a = asked(document_id)
    outcome = orchestrator.resume(a.session_id, option_key="c")

    assert outcome.new_text == "drafted"
    assert outcome.notes == []


def test_a_finished_session_cannot_be_answered_again(document_id, blocking_model):
    a = asked(document_id)
    orchestrator.resume(a.session_id, option_key="c")

    with pytest.raises(orchestrator.SessionFinished):
        orchestrator.resume(a.session_id, option_key="c")


def test_an_unknown_session_is_not_a_crash(blocking_model):
    with pytest.raises(orchestrator.UnknownSession):
        orchestrator.resume("nope", option_key="a")


def test_an_unrecognised_option_is_rejected(document_id, blocking_model):
    a = asked(document_id)
    with pytest.raises(ValueError):
        orchestrator.resume(a.session_id, option_key="z")
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: `AttributeError: module 'app.orchestrator' has no attribute 'resume'`.

- [ ] **Step 3: Append `resume()`**

Add to the imports at the top of `backend/app/orchestrator.py`:

```python
from .conflicts import Conflict, ground, to_notes
from .question import Branch
```

Append:

```python
def hold_constraint(conflicts: list[Conflict], heading: str) -> str:
    """What a second draft is held to when the author says "hold that section".

    Built here, not asked of the model, so what the redraft must honour is a
    string this file's tests can read.
    """
    quotes = " ".join(f'It says "{c.quote}".' for c in conflicts)
    return f"{heading} must stand exactly as written. {quotes} Do not contradict it."


def resume(session_id: str, *, option_key: str) -> Completed | Declined:
    """Only branch (a) needs new text. (b) and (c) are the author approving the
    draft they were shown — returning to the model there would risk handing
    back different text than the one they just accepted.

    Note the return type: no `Asking` arm. Whatever branch (a)'s re-check finds
    becomes a note on the result, never a second question — that guarantee is
    readable from this signature, not from a counter anywhere in the body.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.resolved:
        raise SessionFinished(session_id)

    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # ValueError on anything else, by design
    by_id = {s.id: s for s in document.sections}
    heading = by_id[session.asking[0].section_id].heading

    if branch is Branch.HOLD:
        draft = draft_section(
            sections=document.sections, section_id=session.section_id,
            instruction=session.instruction,
            constraints=[hold_constraint(session.asking, heading)],
        )
        found = find_conflicts(
            sections=document.sections, section_id=session.section_id,
            instruction=session.instruction, new_text=draft.new_text,
        )
        grounded = ground(found, by_id, rewritten_id=session.section_id)
        notes = session.notes + to_notes(found, grounded, by_id)
        new_text = draft.new_text
    else:
        new_text = session.draft_text
        notes = session.notes + (to_notes(session.asking, session.asking, by_id) if branch is Branch.FLAG else [])

    session.resolved = True
    section = find_section(document.sections, session.section_id)
    return Completed(section_id=section.id, old_text=section.text, new_text=new_text, notes=notes)
```

- [ ] **Step 4: Run the orchestrator tests, then remove `loop.py`**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: all pass. Then:

```bash
rm backend/app/loop.py backend/tests/test_loop.py
grep -rln "app\.loop\|from \.loop\|from app import loop" backend/app backend/tests
```

Must return nothing except `main.py` — fixed in Task 9.

- [ ] **Step 5: Commit**

```bash
git add backend/app/orchestrator.py backend/tests/test_orchestrator.py
git rm backend/app/loop.py backend/tests/test_loop.py
git commit -m "$(cat <<'EOF'
Add resume() — Completed | Declined, no Asking arm, on purpose

Replaces loop.py (293 lines) with about 40. The old design capped rounds at two
and tracked which sections had already been asked about to avoid asking twice.
Here there is nothing to cap: resume()'s return type has no Asking arm, so a
second question is not a bug the code avoids at runtime, it is a state the
function cannot express.

Branch (a) still re-checks the redraft — trimming a scope to fit a held fee can
strand a promise made elsewhere — but whatever it finds is folded into the
result's notes, never raised as a second interrupt.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `main.py` — rewired

**Files:**
- Modify: `backend/app/main.py` (in place)
- Modify: `backend/tests/test_api.py` (substantial rewrite of the rewrite/answer sections)

**Interfaces:**
- Produces: `POST /documents`, `POST /rewrite`, `POST /rewrite/{session_id}/answer` — same three
  endpoints. Response shapes:
  ```python
  class RewriteComplete(BaseModel):
      status: Literal["complete"] = "complete"
      section_id: str; old_text: str; new_text: str; notes: list[Note] = []
  class RewriteNeedsClarification(BaseModel):
      status: Literal["needs_clarification"] = "needs_clarification"
      session_id: str; section_id: str; question: str; options: list[Option]
  class RewriteDeclined(BaseModel):
      status: Literal["declined"] = "declined"
      section_id: str; reason: str
  ```
  **No `assumptions` field** — there is nothing to state an assumption about.

- [ ] **Step 1: Rewrite `test_api.py`'s rewrite/answer sections**

Keep the file's upload tests (`test_upload_returns_a_document_id_and_its_sections`,
`test_upload_rejects_a_file_that_is_not_a_docx`, `test_upload_rejects_a_non_docx_extension`)
unchanged — parsing/upload didn't change shape. Replace everything from `# --- rewrite` onward:

```python
# --- rewrite -------------------------------------------------------------


@pytest.fixture
def document_id() -> str:
    return upload(make_docx(PROPOSAL)).json()["document_id"]


NEW_TEXT = "Concrete deliverables: a current-state map."


@pytest.fixture
def fake_model(monkeypatch):
    """Substitute DRAFT and DETECT. Mutate `state["conflicts"]` to script what
    DETECT finds; default is a clean bill of health. The phrasing call fails on
    purpose — wording is test_question.py's business, not this file's."""
    state = {"conflicts": []}

    monkeypatch.setattr(
        "app.rewrite.structured_completion",
        lambda **kw: kw["schema"](applicable=True, new_text=NEW_TEXT),
    )
    monkeypatch.setattr(
        "app.conflicts.structured_completion",
        lambda **kw: kw["schema"](findings=[c.model_dump() for c in state["conflicts"]]),
    )
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return state


def blocking_conflict(**overrides) -> Conflict:
    return Conflict(
        **{
            "section_id": "s3", "quote": "A fixed fee of EUR 48,000",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "blocking": True, **overrides,
        }
    )


def rewrite(document_id: str, section_id: str = "s2", instruction: str = "Be concrete."):
    return client.post("/rewrite", json={
        "document_id": document_id, "section_id": section_id, "instruction": instruction,
    })


def test_rewrite_returns_the_new_text_alongside_the_old(document_id, fake_model):
    response = rewrite(document_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == NEW_TEXT
    assert body["notes"] == []


def test_rewrite_404s_on_an_unknown_document(fake_model):
    response = rewrite("nope")
    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()


def test_rewrite_404s_on_an_unknown_section(document_id, fake_model):
    response = rewrite(document_id, section_id="s99")
    assert response.status_code == 404
    assert "section" in response.json()["detail"].lower()


def test_rewrite_surfaces_a_model_failure_rather_than_a_500(document_id, monkeypatch):
    def refuse(*, system, user, schema, **kwargs):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.rewrite.structured_completion", refuse)
    response = rewrite(document_id)
    assert response.status_code == 502
    assert "model" in response.json()["detail"].lower()


def test_rewrite_rejects_a_blank_instruction(document_id, fake_model):
    response = client.post("/rewrite", json={
        "document_id": document_id, "section_id": "s2", "instruction": "   ",
    })
    assert response.status_code == 422


def test_a_clean_rewrite_completes_with_no_notes(document_id, fake_model):
    assert rewrite(document_id).json()["notes"] == []


def test_a_blocking_finding_suspends_and_asks(document_id, fake_model):
    fake_model["conflicts"] = [blocking_conflict()]
    body = rewrite(document_id).json()
    assert body["status"] == "needs_clarification"
    assert [o["key"] for o in body["options"]] == ["a", "b", "c"]


# --- answering the question ------------------------------------------------


def answer(session_id: str, option_key: str = "c"):
    return client.post(f"/rewrite/{session_id}/answer", json={"option_key": option_key})


@pytest.fixture
def asked(document_id, fake_model):
    fake_model["conflicts"] = [blocking_conflict()]
    body = rewrite(document_id).json()
    assert body["status"] == "needs_clarification"
    return body


def test_answering_completes_the_rewrite(asked):
    response = answer(asked["session_id"], "c")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == NEW_TEXT


def test_answering_never_produces_a_second_question(asked, fake_model):
    """resume()'s return type has no Asking arm — this exercises that at the
    HTTP boundary, where a bug would otherwise be a silently-ignored field."""
    fake_model["conflicts"] = [
        blocking_conflict(section_id="s1", quote="act on this quarter")
    ]
    body = answer(asked["session_id"], "a").json()
    assert body["status"] == "complete"


def test_flagging_keeps_the_finding_as_a_note(asked):
    body = answer(asked["session_id"], "b").json()
    assert [n["section_id"] for n in body["notes"]] == ["s3"]


def test_answering_an_unknown_session_404s(fake_model):
    response = answer("nope")
    assert response.status_code == 404
    assert "session" in response.json()["detail"].lower()


def test_answering_twice_409s(asked):
    answer(asked["session_id"], "c")
    response = answer(asked["session_id"], "c")
    assert response.status_code == 409
    assert "finished" in response.json()["detail"].lower()


def test_an_unrecognised_option_is_a_422(asked):
    assert answer(asked["session_id"], "z").status_code == 422


def test_a_lost_document_is_a_404_not_a_500(asked, monkeypatch):
    monkeypatch.setattr("app.store._DOCUMENTS", {})
    response = answer(asked["session_id"], "c")
    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()


def test_a_model_failure_on_a_redraft_is_a_502(asked, monkeypatch):
    def refuse(*, system, user, schema, **kwargs):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.rewrite.structured_completion", refuse)
    response = answer(asked["session_id"], "a")
    assert response.status_code == 502
```

Update the file's imports at the top: `from app.conflicts import Conflict` replaces
`from app.audit import AuditResult, Finding`.

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: `ModuleNotFoundError` — `main.py` still imports the deleted modules.

- [ ] **Step 3: Rewrite `main.py`**

Replace the imports:

```python
from . import orchestrator, store
from .conflicts import Note
from .llm import ModelRefusal
from .parsing import Section, UnparseableDocument, parse_docx
from .question import Branch, Option
```

Replace `RewriteComplete` (drop `ripples`/`assumptions`, add `notes`):

```python
class RewriteComplete(BaseModel):
    """The rewrite stands. `notes` are consequences the policy judged not worth
    interrupting for — shown so the author can act on them by hand. Never
    applied outside the selected section."""

    status: Literal["complete"] = "complete"
    section_id: str
    old_text: str
    new_text: str
    notes: list[Note] = []
```

`RewriteNeedsClarification` and `RewriteDeclined` are unchanged in shape. Add the `AnswerRequest`
model (same pattern as the prior session's, retyped to the new `Branch`):

```python
class AnswerRequest(BaseModel):
    option_key: str

    @field_validator("option_key")
    @classmethod
    def must_be_a_branch(cls, value: str) -> str:
        try:
            Branch(value)
        except ValueError as exc:
            raise ValueError("option_key must be one of: a, b, c.") from exc
        return value
```

Replace the mapper and both endpoints:

```python
def _to_response(outcome: orchestrator.Outcome) -> RewriteResponse:
    if isinstance(outcome, orchestrator.Declined):
        return RewriteDeclined(section_id=outcome.section_id, reason=outcome.reason)
    if isinstance(outcome, orchestrator.Asking):
        return RewriteNeedsClarification(
            session_id=outcome.session_id, section_id=outcome.section_id,
            question=outcome.question.text, options=outcome.question.options,
        )
    return RewriteComplete(
        section_id=outcome.section_id, old_text=outcome.old_text,
        new_text=outcome.new_text, notes=outcome.notes,
    )


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest) -> RewriteResponse:
    try:
        outcome = orchestrator.start(
            request.document_id, section_id=request.section_id, instruction=request.instruction
        )
    except orchestrator.UnknownDocument as exc:
        raise HTTPException(404, "No document with that id — upload it again.") from exc
    except orchestrator.UnknownSection as exc:
        raise HTTPException(404, "No section with that id in this document.") from exc
    except (ModelRefusal, OpenAIError) as exc:
        raise HTTPException(502, f"The model could not complete this rewrite: {exc}") from exc

    return _to_response(outcome)


@app.post("/rewrite/{session_id}/answer", response_model=RewriteResponse)
async def answer(session_id: str, request: AnswerRequest) -> RewriteResponse:
    try:
        outcome = orchestrator.resume(session_id, option_key=request.option_key)
    except orchestrator.UnknownSession as exc:
        raise HTTPException(404, "No rewrite session with that id — start again.") from exc
    except orchestrator.UnknownDocument as exc:
        raise HTTPException(404, "The document for this rewrite is gone — upload it again.") from exc
    except orchestrator.SessionFinished as exc:
        raise HTTPException(409, "This rewrite has already finished.") from exc
    except (ModelRefusal, OpenAIError) as exc:
        raise HTTPException(502, f"The model could not complete this rewrite: {exc}") from exc

    return _to_response(outcome)
```

(Existing `HTTPException` calls in the file use `status_code=`/`detail=` keyword form — match that
convention rather than the positional form shown above for brevity.)

- [ ] **Step 4: Run the whole suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: all pass, no skips beyond the calibration file's `RUN_LIVE_TESTS` guard (which is broken
until Task 14 — acceptable, since `test_calibration.py` isn't touched until then; if it fails to
*import*, fix that now by updating its imports to `app.conflicts`/`app.orchestrator`, deferring the
live-behavior rewrite to Task 14).

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
Rewire main.py onto orchestrator.py

Same three endpoints, same discriminated response shapes. RewriteComplete drops
ripples and assumptions for a single notes list — there is nothing left to state
an assumption about, since there is no round cap to spend.

test_answering_never_produces_a_second_question exercises resume()'s narrowed
return type at the HTTP boundary, where a regression would otherwise show up as
a silently-ignored response field rather than a type error.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Frontend — `lib/api.ts`

**Files:**
- Modify: `frontend/lib/api.ts`

**Interfaces:**
- Produces: `Note` replaces `Ripple`; `RewriteComplete` drops `assumptions`; `answerQuestion()`'s
  return type narrows to `Promise<RewriteComplete | RewriteDeclined>` — mirroring the backend's
  `resume()` signature, so the same "cannot ask twice" guarantee shows up in the frontend's own type
  checker, not just the API contract.

- [ ] **Step 1: Edit the types and the call**

Replace the `Ripple` type and everything through `answerQuestion`:

```ts
export type Note = {
  section_id: string;
  heading: string;
  quote: string;
  explanation: string;
  /** False when the quoted clause could not be found where the model said it
   *  was — a possibly invented conflict, shown but never asked about. */
  verified: boolean;
};

export type Option = { key: string; label: string };

export type RewriteComplete = {
  status: "complete";
  section_id: string;
  old_text: string;
  new_text: string;
  notes: Note[];
};

export type RewriteNeedsClarification = {
  status: "needs_clarification";
  session_id: string;
  section_id: string;
  question: string;
  options: Option[];
};

export type RewriteDeclined = {
  status: "declined";
  section_id: string;
  reason: string;
};

export type RewriteResult =
  | RewriteComplete
  | RewriteNeedsClarification
  | RewriteDeclined;

export async function rewriteSection(input: {
  documentId: string;
  sectionId: string;
  instruction: string;
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: input.documentId,
        section_id: input.sectionId,
        instruction: input.instruction,
      }),
    }),
  );
}

/** resume() on the backend cannot ask a second question — its return type has
 *  no Asking arm. This return type says the same thing on the client. */
export async function answerQuestion(input: {
  sessionId: string;
  optionKey: string;
}): Promise<RewriteComplete | RewriteDeclined> {
  return unwrap<RewriteComplete | RewriteDeclined>(
    await fetch(`${API_BASE}/rewrite/${input.sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option_key: input.optionKey }),
    }),
  );
}
```

- [ ] **Step 2: Typecheck — it must now fail**

```bash
cd frontend && npx tsc --noEmit
```

Expected: an error in `ResultPanel.tsx` (references `.ripples`, which no longer exists) and possibly
`page.tsx`. That is correct — Task 11 fixes the component, Task 12 confirms `page.tsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "$(cat <<'EOF'
Retype the frontend contract: Note replaces Ripple, no assumptions field

answerQuestion() now returns RewriteComplete | RewriteDeclined — never
needs_clarification — mirroring resume()'s narrowed return type on the backend.
The "cannot ask twice" guarantee is now checked by tsc on this side too, not
only by pytest on the other.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Frontend — `ResultPanel.tsx`

**Files:**
- Modify: `frontend/app/components/ResultPanel.tsx`

- [ ] **Step 1: Rewrite the component**

Keep the before/after grid unchanged. Replace the ripples section with notes, and delete the
assumptions section entirely (nothing produces that field anymore):

```tsx
"use client";

import type { RewriteComplete, Note } from "@/lib/api";

/**
 * A consequence the agent judged not worth interrupting for. Shown, never
 * applied: nothing is written outside the selected section.
 */
function NoteCard({ note }: { note: Note }) {
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">{note.heading}</span>
        {!note.verified && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
            unverified
          </span>
        )}
      </div>
      <p className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-600 italic">
        “{note.quote}”
      </p>
      <p className="mt-2 text-sm text-slate-600">{note.explanation}</p>
    </li>
  );
}

export function ResultPanel({ result }: { result: RewriteComplete }) {
  return (
    <div className="space-y-6 rounded-lg border border-slate-300 bg-white p-6">
      <div>
        <h2 className="mb-4 font-semibold">4. Result</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Before
            </h3>
            <p className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm text-slate-600">
              {result.old_text || "(empty)"}
            </p>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              After
            </h3>
            <p className="whitespace-pre-wrap rounded-md bg-emerald-50 p-3 text-sm text-slate-800">
              {result.new_text}
            </p>
          </section>
        </div>
      </div>

      {result.notes.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Also affected — {result.notes.length}, not applied
          </h3>
          <p className="mt-1 mb-3 text-xs text-slate-500">
            Nothing outside the section you picked has been changed.
          </p>
          <ul className="space-y-2">
            {result.notes.map((note, i) => (
              <NoteCard key={`${note.section_id}-${i}`} note={note} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit
```

Expected: clean, or an error only in `page.tsx` if it still narrows on `assumptions` anywhere (it
doesn't — checked in Task 12).

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/ResultPanel.tsx
git commit -m "$(cat <<'EOF'
ResultPanel: notes replace ripples and assumptions

One list instead of two, matching the backend: there is nothing left to state
an assumption about.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Frontend — confirm `page.tsx` and `QuestionPanel.tsx`

**Files:**
- Modify: `frontend/app/page.tsx` only if `tsc` finds an issue (expected: none — its `handleAnswer`
  already calls `answerQuestion` and stores the result in the same `result` state typed as the
  now-narrower union; the `result?.status === "needs_clarification"` branch simply becomes dead code
  for answers, which is harmless and still correct for the initial `/rewrite` call)
- `QuestionPanel.tsx` — unchanged, still renders one `RewriteNeedsClarification`

- [ ] **Step 1: Typecheck the whole frontend**

```bash
npx tsc --noEmit
```

Expected: clean. If not, the error names the exact line — fix only what it names, nothing
speculative.

- [ ] **Step 2: Build**

```bash
npx next build
```

Expected: succeeds.

- [ ] **Step 3: If no code changed, skip the commit** (nothing to commit — confirmed by `git status`).
  If `page.tsx` needed a fix, commit it with a one-line message naming what `tsc` caught.

---

## Task 13: Two more sample documents, different domains

**Files:**
- Create: `backend/scripts/make_policy_docx.py`
- Create: `backend/scripts/make_charter_docx.py`

**Interfaces:**
- Produces: `backend/sample/remote-work-policy.docx`, `backend/sample/data-platform-charter.docx`.
  Task 14 loads both by path, the same way `test_calibration.py` already loads the proposal.

- [ ] **Step 1: `make_policy_docx.py` — no money vocabulary at all**

An internal remote-work policy where an approval threshold in one section depends on a definition in
another — the kind of conflict `quotes_a_commitment`'s old regex would have missed entirely.

```python
"""Generate the second sample document — an internal policy, deliberately with
no money vocabulary, so the interrupt policy is proven on a domain the old
regex-based commitment check would have missed.

  * §2 defines "regular remote work" as up to three days per week.
  * §3 requires manager approval for anything beyond that definition.
  * §4 sets a documentation deadline of five business days after any change.

Editing §2's definition changes what §3's approval rule is measured against.
"""

from pathlib import Path

from docx import Document

OUTPUT = Path(__file__).resolve().parent.parent / "sample" / "remote-work-policy.docx"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "1. Purpose",
        ["This policy sets out how remote work is arranged and approved."],
    ),
    (
        "2. Definitions",
        [
            "Regular remote work means working from a non-office location up to "
            "three days per week, on a recurring basis.",
        ],
    ),
    (
        "3. Approval",
        [
            "Regular remote work, as defined in section 2, requires no separate "
            "approval beyond the employee's manager confirming the arrangement in "
            "writing. Anything beyond that definition requires HR sign-off.",
        ],
    ),
    (
        "4. Recordkeeping",
        [
            "Any change to a remote work arrangement must be documented within "
            "five business days of the change taking effect.",
        ],
    ),
]


def main() -> None:
    document = Document()
    document.add_paragraph("Remote Work Policy — Internal")
    for heading, paragraphs in SECTIONS:
        document.add_paragraph(heading, style="Heading 1")
        for text in paragraphs:
            document.add_paragraph(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `make_charter_docx.py` — a third domain again**

A short project charter where a rollout date in one section and a scope boundary in another can
collide.

```python
"""Generate the third sample document — a project charter. A rollout date in
one section, a scope boundary in another: neither is money, neither is a
policy threshold, proving the design doesn't lean on either shape.

  * §2 scopes the pilot to a single warehouse.
  * §3 commits to a go-live date that assumes that scope.
  * §4 names the single stakeholder group being trained, tied to the pilot's
    single-warehouse scope.
"""

from pathlib import Path

from docx import Document

OUTPUT = Path(__file__).resolve().parent.parent / "sample" / "data-platform-charter.docx"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "1. Background",
        ["This charter authorises a pilot of the new inventory tracking system."],
    ),
    (
        "2. Scope",
        [
            "The pilot covers the Rotterdam warehouse only. Other sites are "
            "explicitly out of scope for this phase.",
        ],
    ),
    (
        "3. Timeline",
        [
            "Go-live for the Rotterdam warehouse is targeted for the first week "
            "of November, assuming the scope in section 2 holds.",
        ],
    ),
    (
        "4. Training",
        [
            "The Rotterdam warehouse operations team will receive training in "
            "the two weeks before go-live. No other site's staff are scheduled.",
        ],
    ),
]


def main() -> None:
    document = Document()
    document.add_paragraph("Charter: Inventory Tracking Pilot")
    for heading, paragraphs in SECTIONS:
        document.add_paragraph(heading, style="Heading 1")
        for text in paragraphs:
            document.add_paragraph(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate both, confirm they parse**

```bash
./.venv/bin/python -m scripts.make_policy_docx
./.venv/bin/python -m scripts.make_charter_docx
./.venv/bin/python -c "
from app.parsing import parse_docx
for name in ['remote-work-policy.docx', 'data-platform-charter.docx']:
    p = parse_docx(open(f'sample/{name}', 'rb').read())
    print(name, [s.heading for s in p.sections])
"
```

Expected: each prints its four section headings.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/make_policy_docx.py backend/scripts/make_charter_docx.py backend/sample/
git commit -m "$(cat <<'EOF'
Add two more sample documents, deliberately different domains

A remote-work policy (an approval threshold depends on a definition — no money
language anywhere) and a project charter (a go-live date and a training
commitment both depend on a scope boundary). Neither would trip the old design's
quotes_a_commitment regex, which is the point: proving the interrupt policy
holds outside a consulting-proposal vocabulary rather than asserting it does.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Multi-document calibration tests

**Files:**
- Modify: `backend/tests/test_calibration.py` (substantial rewrite)

**Interfaces:**
- Consumes: `orchestrator.start`/`resume`, `conflicts.decide`, all three sample documents.

- [ ] **Step 1: Rewrite the file**

```python
"""Does the interrupt policy fire when it should, across more than one document?

Opt-in, real model, real tokens:

    RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q

The old version of this file tested one document. This one deliberately spans
three, because a design that only works on the vocabulary of one proposal has
not actually been shown to generalize — it has been shown to fit.
"""

import os
from pathlib import Path

import pytest

from app import orchestrator, store
from app.conflicts import decide, find_conflicts
from app.parsing import ParsedDocument, parse_docx
from app.rewrite import draft_section

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"), reason="set RUN_LIVE_TESTS=1 to call the model"
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample"


def load(filename: str):
    path = SAMPLE_DIR / filename
    if not path.exists():
        pytest.skip(f"run the generator for {filename} first")
    return parse_docx(path.read_bytes()).sections


def id_of(sections, heading_fragment: str) -> str:
    return next(s.id for s in sections if heading_fragment in s.heading)


def run(sections, heading_fragment: str, instruction: str):
    section_id = id_of(sections, heading_fragment)
    draft = draft_section(sections=sections, section_id=section_id, instruction=instruction)
    conflicts = find_conflicts(
        sections=sections, section_id=section_id, instruction=instruction, new_text=draft.new_text
    )
    return decide(conflicts, sections, rewritten_id=section_id)


@pytest.fixture(scope="module")
def proposal():
    return load("meridian-proposal.docx")


@pytest.fixture(scope="module")
def policy():
    return load("remote-work-policy.docx")


@pytest.fixture(scope="module")
def charter():
    return load("data-platform-charter.docx")


# --- the proposal: the brief's own example, and the true negative ---------


def test_naming_deliverables_asks_about_the_fixed_fee(proposal):
    decision = run(
        proposal, "Scope of Work",
        "Make this concrete. List the actual deliverables and drop the hedging.",
    )
    assert decision.action == "ask"
    assert id_of(proposal, "Fees") in {c.section_id for c in decision.asking}


def test_tightening_the_summary_prose_asks_nothing(proposal):
    """THE TRUE NEGATIVE. No number, no date, no deliverable, no obligation
    changes. An agent that interrupts here gets switched off."""
    decision = run(proposal, "Executive Summary", "Make this more direct. Cut the hedging.")
    assert decision.action == "complete", [c.explanation for c in decision.asking]


# --- the policy: no money vocabulary anywhere ------------------------------


def test_narrowing_the_remote_work_definition_asks_about_approval(policy):
    """§3's approval rule is measured against §2's definition. Shrinking the
    definition changes what needs HR sign-off — and quotes_a_commitment, the
    old design's money/EUR/fee regex, would never have flagged this."""
    decision = run(
        policy, "Definitions",
        "Narrow this to one day per week instead of three.",
    )
    assert decision.action == "ask"
    assert id_of(policy, "Approval") in {c.section_id for c in decision.asking}


# --- the charter: a date and a training commitment, not a fee --------------


def test_widening_the_pilot_scope_asks_about_the_timeline_or_training(charter):
    """Section 2 is deliberately narrow ("Rotterdam warehouse only"). Widening
    it to more sites should raise a question about at least one of the two
    sections that were written assuming the narrow scope."""
    decision = run(
        charter, "Scope",
        "Expand this to cover all three warehouses, not just Rotterdam.",
    )
    assert decision.action == "ask"
    touched = {c.section_id for c in decision.asking} | {n.section_id for n in decision.notes}
    assert id_of(charter, "Timeline") in touched or id_of(charter, "Training") in touched


# --- the loop terminates, on the document that actually has a conflict -----


def test_the_loop_asks_at_most_once(proposal):
    document_id = store.save_document(ParsedDocument(sections=proposal, headings_detected=True))
    outcome = orchestrator.start(
        document_id, section_id=id_of(proposal, "Scope of Work"),
        instruction="Make this concrete. List the actual deliverables and drop the hedging.",
    )
    if isinstance(outcome, orchestrator.Asking):
        outcome = orchestrator.resume(outcome.session_id, option_key="a")
    assert isinstance(outcome, (orchestrator.Completed, orchestrator.Declined))
```

- [ ] **Step 2: Generate all three documents and run live**

```bash
./.venv/bin/python -m scripts.make_sample_docx
./.venv/bin/python -m scripts.make_policy_docx
./.venv/bin/python -m scripts.make_charter_docx
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

Expected: all pass. If `test_widening_the_pilot_scope_...` or the policy test doesn't ask on the
first try, that is real information — read the model's `explanation` field and either adjust the
instruction to be sharper or accept that this particular case is a true negative and rewrite the
assertion to match what actually happened, the same discipline the old calibration suite used
throughout. **Do not loosen the assertion to force a pass** — a case that turns out to be a true
negative is worth documenting, not hiding.

- [ ] **Step 3: Run the full offline suite once more**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_calibration.py
git commit -m "$(cat <<'EOF'
Calibrate across three documents, not one

The old calibration suite proved the policy worked on the Meridian proposal. It
never showed the policy generalizes, because it was never asked to. This version
adds a remote-work policy (no money vocabulary) and a project charter (a date
and a training commitment, not a fee), plus one loop-termination case.

Whatever the live run actually found is what's asserted — a case that turns out
to be a true negative on a real run is rewritten to match, not forced.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: README and status notes

**Files:**
- Modify: `README.md`
- Modify: `docs/status.md`

- [ ] **Step 1: Rewrite `README.md`**

Following the same shape as before (it is a five-minute read, not a rewrite of the constraint) but
reflecting the new design:

- Status line: this is a restart; link both specs, noting the 2026-08-13 one is superseded and kept
  for its measured findings.
- "How it decides to interrupt you": the new two-concept version — `ground()` + the model's own
  `blocking` judgment — replacing the old `blocking = kind_is_not_merely_descriptive and is_verified
  and not is_resolvable` line with `decide()`'s actual shape.
- "Decisions worth knowing": add "at most one question, ever — provable from `resume()`'s return
  type," and "no silent auto-resolution — every conflict either blocks or becomes a note." Remove any
  line that referred to the two-round cap or the `deriving_quote` double-citation.
- Update the file layout table to the new module list.
- Update the test count to the actual number from Task 14's final full-suite run.
- Note the three sample documents and why (spec §6 verbatim reasoning, condensed).

- [ ] **Step 2: Rewrite `docs/status.md`**

Mark this restart's build order (spec §9) against what's actually done; carry forward the "Verified,
not assumed" section from the old status notes (the Azure mislabelling finding, the whole-document-
context finding) since those facts didn't change; add a new section for what the live calibration
run in Task 14 actually found on the two new documents.

- [ ] **Step 3: Run the full suite one last time, record the real number**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Use this exact count in both documents — do not estimate.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/status.md
git commit -m "$(cat <<'EOF'
Rewrite README and status notes for the simplified design

Reflects orchestrator.py/conflicts.py/rewrite.py in place of loop.py/policy.py/
audit.py/agent.py, the two-concept interrupt policy, the at-most-once
clarification guarantee, and the three sample documents. The prior spec stays
linked for the measured findings it recorded, which still hold.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

**Spec coverage.** §2.1 (ask once) → Tasks 7–8 (`resume`'s return type). §2.2 (no auto-resolve) →
Task 4 (`decide` has only `ask`/`complete`). §2.3 (trust `blocking` directly) → Task 3 (`Conflict`
schema). §2.4 (schema-enforced ids) → Task 3 (`_conflict_schema`). §2.5 (preamble) → Task 1. §2.6
(three documents) → Tasks 13–14. §4.1–4.5 → Tasks 2–4, 7–8 respectively. §6 (generalization
checklist) → Global Constraints + Task 13's document design. §7 (edge cases) → distributed across
Tasks 2, 3–4, 6, 8–9 as noted in each task's rationale. §8 (testing strategy) → the whole plan's test
counts, deliberately lighter than the old suite. §9 (build order) → the task ordering itself.

**Type consistency.** `Conflict` (Task 3) is used unchanged by `conflicts.py`'s own `ground`/`decide`
(Task 4), `question.py` (Task 5), `store.py` (Task 6), and `orchestrator.py` (Tasks 7–8). `Note`
(Task 3) flows the same way into `store.py`, `orchestrator.py`, `main.py` (Task 9), and
`lib/api.ts`/`ResultPanel.tsx` (Tasks 10–11). `Decision` (Task 4) is consumed only by
`orchestrator.py` — `main.py` never sees it directly, matching the old design's boundary between the
policy layer and the HTTP layer.

**Two things a reviewer should notice on purpose.** `resume()`'s return type narrows to
`Completed | Declined` (no `Asking`) starting in Task 8, and that narrowing is echoed on the frontend
in Task 10 — the same guarantee, checked by two different type checkers. And `find_conflicts()` is
never called from `main.py` or `store.py` directly — only from `orchestrator.py` — keeping the
policy/orchestration boundary exactly where the old design also kept it, which is one of the things
worth carrying forward unchanged.

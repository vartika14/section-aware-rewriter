# Phase 4 — Clarification Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume the answer to the clarification question — resume the rewrite along the branch the author picked, cap the loop at two questions, and render every outcome in the browser.

**Architecture:** A new module `app/loop.py` owns the suspendable run and the session lifecycle, exposing `start()` and `resume()` that both return one of three domain outcomes. `main.py` returns to being a pure HTTP surface: validate, map outcomes to responses, translate exceptions to status codes. Only the "hold the other section" branch returns to the model; the other two return the draft the author already approved. Re-audit happens exactly when the text changed.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, `openai` SDK (Azure), Next.js 15 App Router, TypeScript, Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-13-section-rewrite-agent-design.md` — §15 is this plan's source of truth. §14 (verification), §4 (interrupt policy) and §5 (question wording) are the earlier decisions it builds on.

## Global Constraints

- **Python 3.12+**, run via `backend/.venv/bin/python`. Never `pip install` anything new — the dependency list in `backend/requirements.txt` is final for this assignment.
- **Every test in `backend/tests/` runs offline.** The model is substituted at the single seam, `app.llm.structured_completion`, via `monkeypatch.setattr("app.<module>.structured_completion", ...)`. The only exception is `tests/test_calibration.py`, which is skipped unless `RUN_LIVE_TESTS=1`.
- **Findings in tests are hand-built, never recorded from the model.** The policy's job is to be correct about inputs the model might produce, including dishonest ones.
- **No new dependencies, no test framework for the front end.** The front end is verified by `npx tsc --noEmit` and by hand in the browser. Adding Jest/Vitest is out of scope and would spend the remaining budget on scaffolding.
- **The agent never writes outside the selected section.** Ripples are proposed, never applied. No task may violate this.
- **Docstrings explain *why*, not *what*.** Match the register of the existing modules: every non-obvious decision carries its reason inline, because the session is spent defending them.
- **Commit after every task.** Message body explains the reasoning, not the diff. End every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```
- **Full suite must stay green:** `cd backend && ./.venv/bin/python -m pytest tests/ -q` → currently `83 passed, 4 skipped`. The count grows; nothing may go red.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/loop.py` | The suspendable run. `start()`, `resume()`, the three `Outcome` types, the four lookup/state exceptions, and the deterministic constraint and assumption sentences. |
| `backend/tests/test_loop.py` | The phase-4 judgement, tested without HTTP: branch semantics, cap arithmetic, already-asked suppression, ripple carry-over vs. replacement. |
| `frontend/app/components/QuestionPanel.tsx` | Renders the question and its lettered options; reports the chosen key upward. |

**Modified:**

| File | Change |
|---|---|
| `backend/app/question.py` | `Branch` enum; `BRANCHES` keyed by it; `instruction` actually reaches the prompt. |
| `backend/app/policy.py` | `decide()` takes `rewritten_section_id`; `_ripple` becomes public `to_ripple`; the self-reference guard. |
| `backend/app/agent.py` | `draft_rewrite(constraints=...)`. |
| `backend/app/store.py` | `RewriteSession` gains `asked_section_ids` and `completed`. |
| `backend/app/main.py` | Shrinks to validation + mapping; gains `POST /rewrite/{session_id}/answer`; `RewriteComplete` gains `assumptions`. |
| `backend/tests/test_policy.py` | Call sites updated; guard tests added. |
| `backend/tests/test_api.py` | The endpoint contract and the edge-case table. |
| `backend/tests/test_question.py` | Instruction-reaches-the-prompt test. |
| `backend/tests/test_calibration.py` | Call site updated; one live loop-termination case. |
| `frontend/lib/api.ts` | Full response union, `Ripple`, `answerQuestion()`. |
| `frontend/app/components/ResultPanel.tsx` | Ripples, assumptions. |
| `frontend/app/page.tsx` | Switches on `status`; holds the clarification state. |
| `README.md`, `docs/status.md` | Phase 4 marked done, honestly. |

---

## Task 1: Branch enum and the unused instruction

Two small corrections in `question.py`. The branch keys currently carry their meaning only inside a label string, which `loop.py` would have to switch on blind. And `compose_question` accepts an `instruction` it never uses, while its own system prompt forbids re-asking an instruction the model is never shown.

**Files:**
- Modify: `backend/app/question.py:42-46` (`BRANCHES`), `:59-64` (`build_options`), `:118-125` (the user message)
- Test: `backend/tests/test_question.py`

**Interfaces:**
- Produces: `question.Branch` — a `str` `Enum` with members `HOLD = "a"`, `FLAG = "b"`, `ACCEPT = "c"`. Task 5 switches on it. `Branch("a")` returns `Branch.HOLD`; `Branch("z")` raises `ValueError`, which Task 7 turns into a 422.
- Produces: `build_options(group: FindingGroup) -> list[Option]` — unchanged signature, still returns keys `["a", "b", "c"]` in that order.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_question.py`, after the `test_the_branches_do_not_depend_on_the_model_being_reachable` test:

```python
# --- the branches have names, not just keys ------------------------------


def test_each_branch_key_has_a_name_the_resume_path_can_switch_on():
    """`loop.py` must not switch on a bare "a". The meaning lives in one place."""
    assert Branch.HOLD.value == "a"
    assert Branch.FLAG.value == "b"
    assert Branch.ACCEPT.value == "c"


def test_the_branch_keys_and_the_rendered_options_cannot_drift_apart():
    assert [option.key for option in build_options(group())] == [
        branch.value for branch in Branch
    ]


def test_an_unrecognised_key_is_not_a_branch():
    with pytest.raises(ValueError):
        Branch("z")


# --- the instruction reaches the prompt -----------------------------------


def test_the_phrasing_call_is_told_what_the_author_asked_for():
    """The system prompt forbids re-asking the instruction. A model that is never
    shown the instruction cannot honour that."""
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return Question(text='It says "A fixed fee of EUR 48,000". Which way?',
                        options=build_options(group()))

    import app.question

    original = app.question.structured_completion
    app.question.structured_completion = capture
    try:
        compose_question(
            group(),
            sections=SECTIONS,
            instruction="Make this concrete. Name the deliverables.",
        )
    finally:
        app.question.structured_completion = original

    assert "Make this concrete. Name the deliverables." in seen["user"]
```

Add the imports this needs at the top of the file — the existing import line becomes:

```python
import pytest

from app.audit import Finding
from app.parsing import Section
from app.policy import FindingGroup
from app.question import (
    Branch,
    Option,
    Question,
    build_options,
    compose_question,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_question.py -q
```

Expected: `ImportError: cannot import name 'Branch' from 'app.question'`.

- [ ] **Step 3: Add the enum**

In `backend/app/question.py`, add `from enum import Enum` to the imports, then replace the `BRANCHES` block (currently lines 37-46) with:

```python
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
```

- [ ] **Step 4: Key the options off the enum**

Replace the body of `build_options` (currently lines 59-64) with:

```python
def build_options(group: FindingGroup) -> list[Option]:
    """The branches, derived from the group with no model involved."""
    return [
        Option(key=branch.value, label=template.format(heading=group.heading))
        for branch, template in BRANCHES
    ]
```

- [ ] **Step 5: Pass the instruction into the phrasing prompt**

In `compose_question`, replace the `user = (...)` assignment (currently lines 119-125) with:

```python
    conflicting = next((s for s in sections if s.id == group.section_id), None)
    user = (
        f"The author asked for this rewrite: {instruction}\n\n"
        f"It has a consequence for {group.heading}, which currently reads:\n\n"
        f"{conflicting.text if conflicting else ''}\n\n"
        f"---\n\nDrafted question: {deterministic.text}\n\n"
        + "\n".join(f"({o.key}) {o.label}" for o in options)
    )
```

- [ ] **Step 6: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `87 passed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/question.py backend/tests/test_question.py
git commit -m "$(cat <<'EOF'
Name the branches, and show the model the instruction it must not re-ask

The resume path has to switch on what a branch means, and the meaning was living
inside a label string. One enum, in the module that owns the branches.

Separately: compose_question took an instruction it never used, while its system
prompt told the model not to re-ask an instruction it was never shown. Wired in.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: The self-reference guard in the policy

`decide()` receives the document's original sections, including the *old* text of the section being rewritten. So the audit can claim a conflict is resolved by quoting text the draft is about to delete — verification passes, and the finding buys silence on the strength of a sentence that will not exist. Spec §15.10.

Two rules, both in `policy.py`:

1. A resolution grounded in the section being rewritten is not a resolution.
2. A finding whose *own* `section_id` is the section being rewritten is not a cross-section conflict at all, so it can never block. It is still surfaced as a ripple — the audit may have something true to say about the old text, and hiding it is the bug this tool exists to prevent.

**Files:**
- Modify: `backend/app/policy.py:64-98` (`is_resolvable`, `is_blocking`), `:137-147` (`_ripple`), `:166-184` (`decide`)
- Modify: `backend/tests/test_policy.py` (10 `decide(...)` call sites), `backend/tests/test_calibration.py:62`
- Test: `backend/tests/test_policy.py`

**Interfaces:**
- Produces: `decide(audit: AuditResult, sections: list[Section], *, rewritten_section_id: str) -> Decision` — the third argument is **required and keyword-only**. Tasks 4 and 5 call it.
- Produces: `to_ripple(finding: Finding, by_id: dict[str, Section]) -> Ripple` — the former `_ripple`, now public because Task 5 builds ripples outside this module.
- Produces: `is_resolvable(finding, by_id, *, rewritten_section_id: str | None = None) -> bool` and `is_blocking(finding, by_id, *, rewritten_section_id: str | None = None) -> bool` — the keyword defaults to `None` so the existing direct-call tests keep working; `decide` always passes it.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_policy.py`:

```python
# --- the section being rewritten cannot vouch for itself -----------------


def test_a_resolution_grounded_in_the_rewritten_section_is_not_a_resolution():
    """The words doing the resolving are about to be deleted.

    `decide` is handed the document as it stands *before* the rewrite, so a
    citation pointing at the section under edit verifies against text that will
    not survive the change. Trusting it is a silent wrong answer.
    """
    self_grounded = finding(
        resolvable_from_document=True,
        deriving_section_id="s2",
        deriving_quote="The engagement is advisory",
    )

    assert is_resolvable(self_grounded, BY_ID) is True
    assert is_resolvable(self_grounded, BY_ID, rewritten_section_id="s2") is False


def test_a_self_grounded_resolution_falls_closed_to_asking():
    decision = decide(
        audit(findings=[
            finding(
                resolvable_from_document=True,
                deriving_section_id="s2",
                deriving_quote="The engagement is advisory",
            )
        ]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "ask"


def test_a_finding_against_the_rewritten_section_never_blocks():
    """A section cannot conflict with itself; that is just the rewrite."""
    decision = decide(
        audit(findings=[finding(section_id="s2", quote="The engagement is advisory")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert decision.action == "complete"


def test_but_it_is_still_reported_as_a_ripple():
    """Silently dropping it would hide part of the document from the author."""
    decision = decide(
        audit(findings=[finding(section_id="s2", quote="The engagement is advisory")]),
        SECTIONS,
        rewritten_section_id="s2",
    )

    assert [ripple.section_id for ripple in decision.ripples] == ["s2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_policy.py -q
```

Expected: `TypeError: is_resolvable() got an unexpected keyword argument 'rewritten_section_id'`.

- [ ] **Step 3: Add the guard to `is_resolvable`**

In `backend/app/policy.py`, replace `is_resolvable` (currently lines 64-74) with:

```python
def is_resolvable(
    finding: Finding,
    by_id: dict[str, Section],
    *,
    rewritten_section_id: str | None = None,
) -> bool:
    """Can the document settle this without asking anyone?

    The model's `resolvable_from_document` claim is not taken on trust: it must
    cite the section and the exact words that supply the answer, and those words
    must really be there. Anything less fails closed, because this boolean is the
    only thing standing between a conflict and a human never hearing about it.

    A citation pointing at the section being rewritten fails closed too, and for
    a reason the substring check cannot see: this function is handed the document
    as it stands *before* the rewrite, so those words verify and then get deleted.
    A resolution grounded in text that is about to vanish is not a resolution.
    """
    if not finding.resolvable_from_document:
        return False
    if rewritten_section_id and finding.deriving_section_id == rewritten_section_id:
        return False
    return _quotes(finding.deriving_quote, finding.deriving_section_id, by_id)
```

- [ ] **Step 4: Add the guard to `is_blocking`**

Replace `is_blocking` (currently lines 77-98) with:

```python
def is_blocking(
    finding: Finding,
    by_id: dict[str, Section],
    *,
    rewritten_section_id: str | None = None,
) -> bool:
    """The interrupt policy.

    Four ways a finding stays quiet, and they are quiet for different reasons:

    * a finding against the section being rewritten is not a conflict *between*
      sections — it is the rewrite. It cannot be a question, though it is still
      reported, since the audit may have something true to say about the old text;
    * a stale reference is a ripple edit, never a decision — but the label is
      the model's opinion, and it is only honoured for text that describes
      rather than promises. Measured against the real model, a fixed fee whose
      premise had moved came back labelled `stale_reference` on a third of runs,
      which would have walked it silently past this policy. `kind` alone is
      therefore not enough to buy silence;
    * a resolvable conflict has its answer in the document already;
    * an unverified conflict may not be a conflict at all, and interrupting a
      consultant about an imaginary problem is how a tool like this gets
      switched off. It is still reported — see `Ripple.verified` — but it can
      never become a question.
    """
    if rewritten_section_id and finding.section_id == rewritten_section_id:
        return False
    if finding.kind == "stale_reference" and not quotes_a_commitment(finding.quote):
        return False
    if not is_verified(finding, by_id):
        return False
    return not is_resolvable(
        finding, by_id, rewritten_section_id=rewritten_section_id
    )
```

- [ ] **Step 5: Make `_ripple` public and thread the id through `decide`**

Rename `_ripple` to `to_ripple` (line 137) and update its docstring's first line to:

```python
def to_ripple(finding: Finding, by_id: dict[str, Section]) -> Ripple:
    """Build the reportable form of a finding the policy chose not to ask about.

    Public because `loop.py` also demotes findings to ripples — when the author
    says "flag it", and when a group has already been asked about once.
    """
```

Then replace `decide` (currently lines 166-184) with:

```python
def decide(
    audit: AuditResult,
    sections: list[Section],
    *,
    rewritten_section_id: str,
) -> Decision:
    """Turn the audit's evidence into one of three outcomes.

    `rewritten_section_id` is required rather than optional because forgetting it
    silently weakens the verification the whole design rests on — see
    `is_resolvable`.
    """
    if not audit.instruction_applicable:
        return Decision(
            action="decline",
            reason=audit.inapplicable_reason
            or "That instruction does not apply to the selected section.",
        )

    by_id = {section.id: section for section in sections}

    def blocking(finding: Finding) -> bool:
        return is_blocking(finding, by_id, rewritten_section_id=rewritten_section_id)

    return Decision(
        action="ask" if any(blocking(f) for f in audit.findings) else "complete",
        ripples=[to_ripple(f, by_id) for f in audit.findings if not blocking(f)],
        groups=_group([f for f in audit.findings if blocking(f)], by_id),
    )
```

- [ ] **Step 6: Update the existing call sites**

```bash
cd backend && grep -rn "decide(" app tests | grep -v "def decide"
```

There are 12 hits. Update each:

- `app/main.py:138` → `decision = decide(audit, document.sections, rewritten_section_id=request.section_id)`
- `tests/test_calibration.py:62`, inside the `run` helper, which already binds `section_id` on its first line → `return decide(audit, sections, rewritten_section_id=section_id)`
- The 10 hits in `tests/test_policy.py` → add `rewritten_section_id="s2"` as a final keyword argument. `s2` is the Scope of Work section those fixtures rewrite; every finding in them points at `s4`, so the guard changes none of their outcomes.

- [ ] **Step 7: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `91 passed, 4 skipped`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/policy.py backend/tests/test_policy.py backend/tests/test_calibration.py backend/app/main.py
git commit -m "$(cat <<'EOF'
Stop the rewritten section from vouching for itself

decide() is handed the document as it stands before the rewrite, so a finding
claiming "the section being edited already resolves this" verified against text
the draft was about to delete — and bought silence with it. That is the one
failure the verification in §14.2 exists to prevent, reachable through the one
section it never checked.

Two rules. A resolution grounded in the section under edit fails closed. A
finding against that section can never block, since a section does not conflict
with itself — but it is still reported as a ripple rather than dropped.

rewritten_section_id is required rather than optional: forgetting it weakens the
check silently, which is the worst way for a safeguard to fail.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `draft_rewrite` accepts constraints

Branch (a) re-drafts under an added constraint. DRAFT needs somewhere to put it. Spec §15.3.

**Files:**
- Modify: `backend/app/agent.py:57-75`
- Test: `backend/tests/test_agent.py`

**Interfaces:**
- Produces: `draft_rewrite(*, sections: list[Section], section_id: str, instruction: str, constraints: Sequence[str] = ()) -> Draft`. Task 5 passes a one-element list.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agent.py`:

```python
# --- constraints on a second draft ---------------------------------------


def test_a_constraint_reaches_the_model(monkeypatch):
    """Branch (a) re-drafts under something the author has just insisted on.
    If it does not reach the prompt, the second draft is the first one again."""
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(new_text="trimmed")

    monkeypatch.setattr("app.agent.structured_completion", capture)

    draft_rewrite(
        sections=SECTIONS,
        section_id="s2",
        instruction="Make this concrete.",
        constraints=["4. Fees must stand exactly as written."],
    )

    assert "4. Fees must stand exactly as written." in seen["user"]


def test_no_constraints_leaves_the_prompt_as_it_was(monkeypatch):
    """The first draft must not grow a stray empty section."""
    seen = {}

    def capture(*, system, user, schema, **kwargs):
        seen["user"] = user
        return schema(new_text="drafted")

    monkeypatch.setattr("app.agent.structured_completion", capture)

    draft_rewrite(
        sections=SECTIONS, section_id="s2", instruction="Make this concrete."
    )

    assert "must hold" not in seen["user"]
```

No new imports or fixtures are needed: `backend/tests/test_agent.py:10-17` already imports `draft_rewrite` and defines `SECTIONS` with `s2` as "2. Scope of Work".

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_agent.py -q
```

Expected: `TypeError: draft_rewrite() got an unexpected keyword argument 'constraints'`.

- [ ] **Step 3: Add the parameter**

In `backend/app/agent.py`, add `from collections.abc import Sequence` to the imports, then replace `draft_rewrite` (currently lines 57-75) with:

```python
def draft_rewrite(
    *,
    sections: list[Section],
    section_id: str,
    instruction: str,
    constraints: Sequence[str] = (),
) -> Draft:
    """Rewrite one section.

    `constraints` carries anything the author has since insisted on — on a second
    draft, that the clause they chose to hold must survive intact. They are built
    in Python from the finding group, never asked for, so what the second draft is
    held to can be unit tested. An empty default keeps the first draft's prompt
    exactly as it was.
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

    # Pinned to 0 like the audit, and for the same reason once removed: the
    # audit's only input is this draft, so a draft that varies makes the
    # decision to interrupt vary with it. A consultant who reruns a rewrite and
    # gets a question the second time has learned not to trust either answer.
    return structured_completion(
        system=SYSTEM, user=user, schema=Draft, temperature=0
    )
```

- [ ] **Step 4: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `93 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent.py backend/tests/test_agent.py
git commit -m "$(cat <<'EOF'
Let DRAFT take constraints, for the second draft

Branch (a) rewrites again under something the author has just insisted on. The
constraint is built in Python from the finding group rather than asked for, so
what the second draft is held to can be tested without a network.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Extract `loop.start()` — pure refactor

Move the `/rewrite` body out of the HTTP layer with no behaviour change. Every existing test must pass untouched; that is the whole exit criterion. Spec §15.8.

**Files:**
- Create: `backend/app/loop.py`
- Modify: `backend/app/main.py:104-175` (the `rewrite` handler), `:68-101` (response models)
- Modify: `backend/app/store.py:22-36` (`RewriteSession`)

**Interfaces:**
- Consumes: `decide(..., rewritten_section_id=...)` and `to_ripple(...)` from Task 2; `Branch` from Task 1.
- Produces:
  ```python
  class Completed(BaseModel):
      section_id: str
      old_text: str
      new_text: str
      ripples: list[Ripple] = []
      assumptions: list[str] = []

  class Asking(BaseModel):
      session_id: str
      section_id: str
      question: Question

  class Declined(BaseModel):
      section_id: str
      reason: str

  Outcome = Completed | Asking | Declined

  class UnknownDocument(LookupError): ...
  class UnknownSection(LookupError): ...
  class UnknownSession(LookupError): ...
  class SessionFinished(RuntimeError): ...

  def start(document_id: str, *, section_id: str, instruction: str) -> Outcome
  ```
  Task 5 adds `resume`; Task 7 maps all of these to HTTP.
- Produces: `store.RewriteSession` gains `asked_section_ids: list[str] = []` and `completed: bool = False`.

- [ ] **Step 1: Extend the session record**

In `backend/app/store.py`, replace the `RewriteSession` class (currently lines 22-36) with:

```python
class RewriteSession(BaseModel):
    """A rewrite that stopped to ask something, and everything needed to finish.

    `draft_text` is kept so the answer resumes from a rewrite that already
    exists rather than re-running the draft blind, and `groups` is kept because
    the answer only means anything against the question it was asked.

    Invariant: `groups[0]` is the group currently being asked about. The rest are
    what a second round would draw from.

    `asked_section_ids` is what stops the same question being asked twice — a
    second draft can fail to honour its constraint and hand back the identical
    finding, and re-asking would tell the author the tool was not listening.
    `completed` makes a finished session terminal, so a stale tab answering twice
    gets a clear 409 rather than silently re-running the loop.
    """

    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    groups: list[FindingGroup]
    ripples: list[Ripple]
    answers: list[str] = []
    asked_section_ids: list[str] = []
    completed: bool = False
```

- [ ] **Step 2: Create `loop.py` with `start()`**

Create `backend/app/loop.py`:

```python
"""The suspendable run.

DRAFT → AUDIT → DECIDE, and then either a result or a question. This module owns
the run and the session that outlives it; `main.py` owns nothing but HTTP.

The split matters because the interesting decisions live here — which branch
re-drafts, when to audit again, when to stop asking — and logic reachable only
through a `TestClient` is logic that does not get tested properly. The run still
suspends by returning, exactly as the design specced: no state machine, no queue.
"""

from pydantic import BaseModel

from . import store
from .agent import draft_rewrite, find_section
from .audit import audit_rewrite
from .policy import Ripple, decide
from .question import Question, compose_question


class UnknownDocument(LookupError):
    """The document is not in the store — never uploaded, or lost to a restart."""


class UnknownSection(LookupError):
    """No section with that id in this document."""


class UnknownSession(LookupError):
    """No suspended rewrite with that id."""


class SessionFinished(RuntimeError):
    """This rewrite already finished. The stale-tab case."""


class Completed(BaseModel):
    """The rewrite stands.

    `ripples` are consequences the policy judged not worth interrupting for.
    `assumptions` are decisions the agent made *instead of* asking, once the
    two-question cap was spent — a separate field rather than another ripple,
    because burying them among proposed edits would hide the one thing the design
    promises to state out loud.
    """

    section_id: str
    old_text: str
    new_text: str
    ripples: list[Ripple] = []
    assumptions: list[str] = []


class Asking(BaseModel):
    """The run suspended. It resumes when the author picks an option."""

    session_id: str
    section_id: str
    question: Question


class Declined(BaseModel):
    """The instruction made no sense for this section, so nothing was written."""

    section_id: str
    reason: str


Outcome = Completed | Asking | Declined


def start(document_id: str, *, section_id: str, instruction: str) -> Outcome:
    """First round: draft, audit, decide."""
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    try:
        section = find_section(document.sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_rewrite(
        sections=document.sections, section_id=section_id, instruction=instruction
    )
    audit = audit_rewrite(
        sections=document.sections,
        section_id=section_id,
        instruction=instruction,
        new_text=draft.new_text,
    )
    decision = decide(audit, document.sections, rewritten_section_id=section_id)

    if decision.action == "decline":
        return Declined(
            section_id=section.id,
            reason=decision.reason or "",
        )

    if decision.action == "complete":
        return Completed(
            section_id=section.id,
            old_text=section.text,
            new_text=draft.new_text,
            ripples=decision.ripples,
        )

    # Suspend. One question per round, so the first group is asked now and any
    # others wait — a human asked four questions stops reading at the second.
    asked = decision.groups[0]
    question = compose_question(
        asked, sections=document.sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id,
            section_id=section_id,
            instruction=instruction,
            draft_text=draft.new_text,
            groups=decision.groups,
            ripples=decision.ripples,
            asked_section_ids=[asked.section_id],
        )
    )

    return Asking(
        session_id=session_id, section_id=section.id, question=question
    )
```

- [ ] **Step 3: Reduce `main.py` to mapping**

In `backend/app/main.py`, replace the imports block (currently lines 7-20) with:

```python
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, field_validator

from . import loop, store
from .llm import ModelRefusal
from .parsing import Section, UnparseableDocument, parse_docx
from .policy import Ripple
from .question import Option
```

Add `assumptions` to `RewriteComplete` (currently lines 68-76):

```python
class RewriteComplete(BaseModel):
    """The rewrite stands. `ripples` are the consequences the policy judged not
    worth interrupting for — shown so the consultant can act on them by hand.
    `assumptions` are what the agent decided once it had spent its two questions,
    stated rather than buried."""

    status: Literal["complete"] = "complete"
    section_id: str
    old_text: str
    new_text: str
    ripples: list[Ripple] = []
    assumptions: list[str] = []
```

Then replace the whole `rewrite` handler (currently lines 104-175) with:

```python
def _to_response(outcome: loop.Outcome) -> RewriteResponse:
    """One mapper, so both endpoints answer in the same shapes."""
    if isinstance(outcome, loop.Declined):
        return RewriteDeclined(section_id=outcome.section_id, reason=outcome.reason)
    if isinstance(outcome, loop.Asking):
        return RewriteNeedsClarification(
            session_id=outcome.session_id,
            section_id=outcome.section_id,
            question=outcome.question.text,
            options=outcome.question.options,
        )
    return RewriteComplete(
        section_id=outcome.section_id,
        old_text=outcome.old_text,
        new_text=outcome.new_text,
        ripples=outcome.ripples,
        assumptions=outcome.assumptions,
    )


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest) -> RewriteResponse:
    try:
        outcome = loop.start(
            request.document_id,
            section_id=request.section_id,
            instruction=request.instruction,
        )
    except loop.UnknownDocument as exc:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        ) from exc
    except loop.UnknownSection as exc:
        raise HTTPException(
            status_code=404, detail="No section with that id in this document."
        ) from exc
    except (ModelRefusal, OpenAIError) as exc:
        # A refusal, a content filter or a transport error is an expected
        # operating condition for this app, not a crash. Say so plainly.
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    return _to_response(outcome)
```

- [ ] **Step 4: Run the whole suite, unchanged**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `93 passed, 4 skipped`. **No test file was edited in this task.** If any test needed changing, the refactor changed behaviour — stop and find out why.

- [ ] **Step 5: Commit**

```bash
git add backend/app/loop.py backend/app/main.py backend/app/store.py
git commit -m "$(cat <<'EOF'
Move the run out of the HTTP layer

main.py's docstring says "HTTP surface"; its rewrite handler had become the
pipeline. Extracted to loop.py, which will also own resume — the branch
semantics and the two-question cap are the phase-4 equivalent of policy.py, and
they deserve tests that do not go through a TestClient to reach them.

Pure refactor: no test file changed.

The session record gains asked_section_ids and completed, which resume needs.
Documented the groups[0] invariant while it is still only read from one place.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `loop.resume()` — the three branches

The heart of phase 4. Spec §15.1–15.4. No cap yet — that is Task 6.

**Files:**
- Modify: `backend/app/loop.py`
- Test: `backend/tests/test_loop.py` (create)

**Interfaces:**
- Consumes: `Branch` (Task 1), `to_ripple` and `decide(rewritten_section_id=...)` (Task 2), `draft_rewrite(constraints=...)` (Task 3), the outcome types and exceptions (Task 4).
- Produces:
  ```python
  def hold_constraint(group: FindingGroup) -> str
  def resume(session_id: str, *, option_key: str) -> Outcome
  ```
  `resume` raises `ValueError` for an unrecognised `option_key`; Task 7 turns that into a 422.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_loop.py`:

```python
"""Tests for the suspendable run.

The clarification loop's judgement lives here — which branch re-drafts, when the
text gets audited again, when the agent stops asking — so it is tested the way
`test_policy.py` tests the interrupt policy: hand-built inputs, no HTTP, no
network. What the endpoint returns is `test_api.py`'s business.

The three branches mean genuinely different things, and the central assertion in
this file is that two of them never go back to the model. An author who clicks
"make the rewrite" and receives different text than the one they were shown has
been given the worst surprise an editing tool has to offer.
"""

import pytest

from app import loop, store
from app.audit import AuditResult, Finding
from app.parsing import ParsedDocument, Section

SECTIONS = [
    Section(
        id="s1",
        heading="1. Executive Summary",
        text="We will deliver a recommendation within the quarter.",
    ),
    Section(
        id="s2",
        heading="2. Scope of Work",
        text="The engagement is advisory; implementation is out of scope.",
    ),
    Section(
        id="s3",
        heading="3. Approach and Timeline",
        text="The engagement runs over eight weeks in three phases.",
    ),
    Section(
        id="s4",
        heading="4. Fees and Payment",
        text="A fixed fee of EUR 48,000 covers the engagement in full. The fee "
        "assumes the scope set out in section 2.",
    ),
]

FIRST_DRAFT = "Three deliverables: a map, a benchmark and a review."
SECOND_DRAFT = "Two deliverables: a map and a benchmark."


def fee_finding(**overrides) -> Finding:
    """Verified and unresolvable — the shape that asks."""
    return Finding(
        **{
            "section_id": "s4",
            "quote": "A fixed fee of EUR 48,000",
            "kind": "invalidated_premise",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


def timeline_finding(**overrides) -> Finding:
    """A second, independent conflict — a different section, so a second group."""
    return Finding(
        **{
            "section_id": "s3",
            "quote": "eight weeks in three phases",
            "kind": "contradiction",
            "explanation": "The new scope names four workstreams, not three.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


@pytest.fixture
def document_id() -> str:
    return store.save_document(
        ParsedDocument(sections=SECTIONS, headings_detected=True)
    )


@pytest.fixture
def model(monkeypatch):
    """Script the pipeline and count what it called.

    `drafts` is a queue: the first draft is popped for round one, the second for
    a branch (a) redraft. `audits` is the same for audit results. `calls` records
    every model call so a test can assert one did NOT happen — which is the point
    of branches (b) and (c).
    """
    state = {
        "drafts": [FIRST_DRAFT, SECOND_DRAFT],
        "audits": [
            AuditResult(instruction_applicable=True, findings=[fee_finding()]),
            AuditResult(instruction_applicable=True, findings=[]),
        ],
        "calls": [],
    }

    def draft(**kwargs):
        state["calls"].append("draft")
        return kwargs["schema"](new_text=state["drafts"].pop(0))

    def audit(**kwargs):
        state["calls"].append("audit")
        return state["audits"].pop(0)

    monkeypatch.setattr("app.agent.structured_completion", draft)
    monkeypatch.setattr("app.audit.structured_completion", audit)
    # The phrasing call fails on purpose: these tests assert on the loop, not on
    # how the sentence reads. `test_question.py` owns the wording.
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return state


def ask(document_id: str) -> loop.Asking:
    outcome = loop.start(
        document_id, section_id="s2", instruction="Make this concrete."
    )
    assert isinstance(outcome, loop.Asking)
    return outcome


# --- branch (a): hold the other section ----------------------------------


def test_holding_the_other_section_produces_a_second_draft(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="a")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == SECOND_DRAFT


def test_the_second_draft_is_told_what_it_must_not_break(document_id, model):
    """A constraint the model never sees is a constraint that does nothing."""
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="a")

    assert "4. Fees and Payment" in loop.hold_constraint(
        store.get_session(asking.session_id).groups[0]
    )


def test_holding_audits_the_new_text(document_id, model):
    """The text is new and unchecked. Trimming the scope to fit the fee can
    break the summary, which is a conflict that did not exist a moment ago."""
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="a")

    assert model["calls"] == ["draft", "audit", "draft", "audit"]


# --- branches (b) and (c): the draft the author already approved ---------


def test_flagging_returns_the_stored_draft_untouched(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="b")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == FIRST_DRAFT


def test_flagging_calls_the_model_not_at_all(document_id, model):
    """The author said "make the rewrite" — the one they were shown. Going back
    to the model risks returning different text than the text they accepted."""
    asking = ask(document_id)
    model["calls"].clear()

    loop.resume(asking.session_id, option_key="b")

    assert model["calls"] == []


def test_flagging_reports_the_finding_as_a_ripple(document_id, model):
    asking = ask(document_id)

    outcome = loop.resume(asking.session_id, option_key="b")

    assert [ripple.section_id for ripple in outcome.ripples] == ["s4"]
    assert outcome.ripples[0].quote == "A fixed fee of EUR 48,000"


def test_accepting_returns_the_stored_draft_and_says_nothing(document_id, model):
    asking = ask(document_id)
    model["calls"].clear()

    outcome = loop.resume(asking.session_id, option_key="c")

    assert isinstance(outcome, loop.Completed)
    assert outcome.new_text == FIRST_DRAFT
    assert outcome.ripples == []
    assert model["calls"] == []


# --- the answer is recorded, and the session becomes terminal -------------


def test_the_answer_is_recorded_on_the_session(document_id, model):
    asking = ask(document_id)

    loop.resume(asking.session_id, option_key="c")

    assert store.get_session(asking.session_id).answers == ["c"]


def test_a_finished_session_cannot_be_answered_again(document_id, model):
    """The stale-tab case: a second click must not re-run the loop."""
    asking = ask(document_id)
    loop.resume(asking.session_id, option_key="c")

    with pytest.raises(loop.SessionFinished):
        loop.resume(asking.session_id, option_key="c")


def test_an_unknown_session_is_not_a_crash(model):
    with pytest.raises(loop.UnknownSession):
        loop.resume("nope", option_key="a")


def test_an_unrecognised_option_is_rejected(document_id, model):
    asking = ask(document_id)

    with pytest.raises(ValueError):
        loop.resume(asking.session_id, option_key="z")


def test_a_failed_redraft_does_not_consume_the_answer(document_id, model, monkeypatch):
    """A 502 mid-resume must leave the session retryable, not half-spent."""
    asking = ask(document_id)

    def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr("app.agent.structured_completion", boom)

    with pytest.raises(RuntimeError):
        loop.resume(asking.session_id, option_key="a")

    session = store.get_session(asking.session_id)
    assert session.answers == []
    assert session.completed is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_loop.py -q
```

Expected: `AttributeError: module 'app.loop' has no attribute 'resume'`.

- [ ] **Step 3: Implement `hold_constraint` and `resume`**

Append to `backend/app/loop.py`. Add these to the imports at the top of the file:

```python
from .policy import FindingGroup, Ripple, decide, to_ripple
from .question import Branch, Question, compose_question
```

(replacing the two existing `from .policy` / `from .question` lines), then append:

```python
def hold_constraint(group: FindingGroup) -> str:
    """What a second draft is held to when the author says "hold that section".

    Built here rather than asked of the model, so what the redraft must honour is
    a string this file's tests can read. It quotes the clause, because a
    constraint the model has to infer is one it can talk itself out of.
    """
    quotes = " ".join(f'It says "{finding.quote}".' for finding in group.findings)
    return (
        f"{group.heading} must stand exactly as written. {quotes} "
        f"Shape the rewrite so this remains true, and do not contradict it."
    )


def resume(session_id: str, *, option_key: str) -> Outcome:
    """Second half of the loop: the author picked a branch.

    Only one branch of three needs new text. "Hold the other section" is the
    author changing their mind about the rewrite; "flag it" and "leave it" are
    the author approving the draft they were shown, and returning to the model
    there would risk handing back something else.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.completed:
        raise SessionFinished(session_id)

    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # ValueError on anything else, by design
    asked, remaining = session.groups[0], session.groups[1:]
    by_id = {section.id: section for section in document.sections}

    if branch is Branch.HOLD:
        # New text, so it gets audited. The audit is given the ORIGINAL
        # instruction and not the constraint: if the redraft failed to honour the
        # held clause, a neutral reviewer flags it again, which is correct. An
        # audit told what the draft was trying to do is inclined to grant that it
        # succeeded.
        draft = draft_rewrite(
            sections=document.sections,
            section_id=session.section_id,
            instruction=session.instruction,
            constraints=[hold_constraint(asked)],
        )
        audit = audit_rewrite(
            sections=document.sections,
            section_id=session.section_id,
            instruction=session.instruction,
            new_text=draft.new_text,
        )
        # `instruction_applicable` is honoured in `start` and ignored here. Round
        # one already established that the instruction applies; a flip now is far
        # more likely model noise than a real reversal, and acting on it would
        # discard work the author has already answered a question about.
        decision = decide(
            audit, document.sections, rewritten_section_id=session.section_id
        )
        new_text = draft.new_text
        ripples = list(decision.ripples)
        groups = list(decision.groups)
    else:
        # Byte-identical to text that was already audited, so auditing it again
        # would spend a call to ask the same question of the same words.
        new_text = session.draft_text
        ripples = list(session.ripples)
        groups = list(remaining)
        if branch is Branch.FLAG:
            ripples.extend(to_ripple(finding, by_id) for finding in asked.findings)

    # Only now: every model call has returned, so a failure above leaves the
    # session exactly as it was and the author can retry without burning a round.
    session.answers.append(option_key)
    session.draft_text = new_text
    session.ripples = ripples
    session.groups = groups
    session.completed = True

    section = find_section(document.sections, session.section_id)
    return Completed(
        section_id=section.id,
        old_text=section.text,
        new_text=new_text,
        ripples=ripples,
    )
```

- [ ] **Step 4: Run the loop tests**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_loop.py -q
```

Expected: PASS, 13 tests.

- [ ] **Step 5: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `106 passed, 4 skipped`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/loop.py backend/tests/test_loop.py
git commit -m "$(cat <<'EOF'
Consume the answer: the three branches

Only one branch of three returns to the model. "Hold that section as written" is
the author changing their mind about the rewrite, so it re-drafts under a
constraint built in Python and then audits the new text. "Flag it" and "leave
it" are the author approving the draft they were shown — going back to the model
there would risk handing back text different from the one they just accepted,
which is the worst surprise an editing tool has to offer.

Re-audit follows the same rule: audit exactly when the text changed.

The redraft's audit is deliberately given the original instruction rather than
the constraint. If the second draft failed to honour the held clause, a neutral
reviewer flags it again — an audit told what the draft was trying to do is
inclined to grant that it succeeded.

The answer is recorded only after every model call returns, so a 502 mid-resume
leaves the session retryable rather than half-spent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: The cap, the assumptions, and never asking twice

Task 5 always completes. Now it can suspend a second time — but only once more, and never about a section it already asked about. Spec §15.5–15.6.

**Files:**
- Modify: `backend/app/loop.py` (`resume`)
- Test: `backend/tests/test_loop.py`

**Interfaces:**
- Produces: `assumption_for(group: FindingGroup) -> str`.
- `resume` may now return `Asking` as well as `Completed`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_loop.py`:

```python
# --- a second round, and then no more ------------------------------------


def test_a_leftover_group_becomes_the_second_question(document_id, model):
    """Two conflicts in two sections: one is asked now, one waits its turn."""
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding()],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")

    assert isinstance(second, loop.Asking)
    assert "3. Approach and Timeline" in second.question.text


def test_a_conflict_the_answer_created_becomes_the_second_question(document_id, model):
    """Hold the fee, trim the scope to fit — and now the summary is wrong.

    That conflict did not exist when the first question was asked. Only a fresh
    audit finds it, which is the whole argument for re-auditing after (a).
    """
    model["audits"] = [
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
        AuditResult(
            instruction_applicable=True,
            findings=[
                Finding(
                    section_id="s1",
                    quote="a recommendation within the quarter",
                    kind="invalidated_premise",
                    explanation="The trimmed scope no longer supports the promise.",
                    resolvable_from_document=False,
                )
            ],
        ),
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="a")

    assert isinstance(second, loop.Asking)
    assert "1. Executive Summary" in second.question.text


def test_the_same_section_is_never_asked_about_twice(document_id, model):
    """A redraft can fail its constraint and hand back the identical finding.
    Re-asking would tell the author the tool was not listening."""
    model["audits"] = [
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
        AuditResult(instruction_applicable=True, findings=[fee_finding()]),
    ]

    asking = ask(document_id)
    outcome = loop.resume(asking.session_id, option_key="a")

    assert isinstance(outcome, loop.Completed)
    assert [ripple.section_id for ripple in outcome.ripples] == ["s4"]


def test_two_questions_is_the_limit(document_id, model):
    """Three conflicts, three sections, and still only two questions."""
    third = Finding(
        section_id="s1",
        quote="a recommendation within the quarter",
        kind="invalidated_premise",
        explanation="The summary promises what the new scope drops.",
        resolvable_from_document=False,
    )
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding(), third],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")
    assert isinstance(second, loop.Asking)

    third_outcome = loop.resume(second.session_id, option_key="c")
    assert isinstance(third_outcome, loop.Completed)


def test_what_the_cap_decided_is_stated_not_buried(document_id, model):
    third = Finding(
        section_id="s1",
        quote="a recommendation within the quarter",
        kind="invalidated_premise",
        explanation="The summary promises what the new scope drops.",
        resolvable_from_document=False,
    )
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding(), third],
        )
    ]

    asking = ask(document_id)
    second = loop.resume(asking.session_id, option_key="c")
    final = loop.resume(second.session_id, option_key="c")

    assert final.assumptions == [
        "Proceeding with the rewrite; 1. Executive Summary left as it stands."
    ]


def test_a_session_that_asks_again_is_not_yet_finished(document_id, model):
    model["audits"] = [
        AuditResult(
            instruction_applicable=True,
            findings=[fee_finding(), timeline_finding()],
        )
    ]

    asking = ask(document_id)
    loop.resume(asking.session_id, option_key="c")

    assert store.get_session(asking.session_id).completed is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_loop.py -q
```

Expected: several failures, the first being `assert isinstance(second, loop.Asking)` receiving a `Completed`.

- [ ] **Step 3: Add `assumption_for`**

Append to `backend/app/loop.py`, next to `hold_constraint`:

```python
def assumption_for(group: FindingGroup) -> str:
    """What the agent decided once it had spent its two questions.

    Stated on the result rather than added to the ripples: a ripple is something
    the author may act on, an assumption is something the agent already acted on.
    Conflating them hides the one thing the two-question cap owes the author.
    """
    return f"Proceeding with the rewrite; {group.heading} left as it stands."
```

- [ ] **Step 4: Replace the tail of `resume`**

In `backend/app/loop.py`, replace everything from `    # Only now: every model call has returned` to the end of `resume` with:

```python
    # Only now: every model call has returned, so a failure above leaves the
    # session exactly as it was and the author can retry without burning a round.
    session.answers.append(option_key)
    session.draft_text = new_text

    # A group naming a section already asked about is demoted rather than raised
    # again. Branch (a) can redraft, miss its constraint, and produce the
    # identical finding; re-asking would say the tool was not listening.
    fresh = [g for g in groups if g.section_id not in session.asked_section_ids]
    ripples.extend(
        to_ripple(finding, by_id)
        for group in groups
        if group.section_id in session.asked_section_ids
        for finding in group.findings
    )

    session.ripples = ripples
    session.groups = fresh

    # Two questions, ever. `answers` already holds this round's, so one answer
    # means a second question is still allowed and two means the cap is spent.
    if fresh and len(session.answers) < 2:
        session.asked_section_ids.append(fresh[0].section_id)
        return Asking(
            session_id=session_id,
            section_id=session.section_id,
            question=compose_question(
                fresh[0],
                sections=document.sections,
                instruction=session.instruction,
            ),
        )

    session.completed = True
    section = find_section(document.sections, session.section_id)
    return Completed(
        section_id=section.id,
        old_text=section.text,
        new_text=new_text,
        ripples=ripples,
        assumptions=[assumption_for(group) for group in fresh],
    )
```

- [ ] **Step 5: Run the loop tests**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_loop.py -q
```

Expected: PASS, 19 tests.

- [ ] **Step 6: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `112 passed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/loop.py backend/tests/test_loop.py
git commit -m "$(cat <<'EOF'
Cap the loop at two questions, and say what was assumed

A second question can come from either of two places, and both matter: a group
left unasked in round one, or a conflict the author's own answer created. Hold
the fee, trim the scope to fit, and the executive summary is now wrong — that
did not exist when the first question was asked, and only the re-audit finds it.

A section already asked about is never asked about again. Branch (a) can redraft,
miss its constraint and produce the identical finding; re-asking would tell the
author the tool was not listening. It is demoted to a ripple, so it is still
visible.

Beyond two questions the agent proceeds and states its assumption on the result
rather than adding it to the ripples — a ripple is something the author may act
on, an assumption is something the agent already acted on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `POST /rewrite/{session_id}/answer`

The HTTP surface for the loop, plus every row of the spec's §15.9 edge-case table.

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `POST /rewrite/{session_id}/answer` with body `{"option_key": "a" | "b" | "c"}`, returning the same `RewriteResponse` union as `POST /rewrite`. Task 8 consumes this.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
# --- answering the question ----------------------------------------------


def answer(session_id: str, option_key: str = "c"):
    return client.post(
        f"/rewrite/{session_id}/answer", json={"option_key": option_key}
    )


@pytest.fixture
def asked(document_id, fake_model):
    """A suspended rewrite, ready to be answered."""
    fake_model["result"] = AuditResult(
        instruction_applicable=True, findings=[blocking_finding()]
    )
    body = rewrite(document_id).json()
    assert body["status"] == "needs_clarification"
    return body


def test_answering_completes_the_rewrite(asked):
    response = answer(asked["session_id"], "c")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == NEW_TEXT
    assert body["assumptions"] == []


def test_flagging_returns_the_finding_as_a_ripple(asked):
    body = answer(asked["session_id"], "b").json()

    assert [ripple["section_id"] for ripple in body["ripples"]] == ["s3"]


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
    response = answer(asked["session_id"], "z")

    assert response.status_code == 422


def test_a_lost_document_is_a_404_not_a_500(asked, monkeypatch):
    """State is in memory. A restart between question and answer is real."""
    monkeypatch.setattr("app.store._DOCUMENTS", {})

    response = answer(asked["session_id"], "c")

    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()


def test_a_model_failure_on_a_redraft_is_a_502(asked, monkeypatch):
    def refuse(*, system, user, schema, **kwargs):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.agent.structured_completion", refuse)

    response = answer(asked["session_id"], "a")

    assert response.status_code == 502
    assert "model" in response.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: `404` on the first test — the route does not exist.

- [ ] **Step 3: Add the request model**

In `backend/app/main.py`, add `Branch` to the question import:

```python
from .question import Branch, Option
```

Then add, after `RewriteRequest`:

```python
class AnswerRequest(BaseModel):
    option_key: str

    @field_validator("option_key")
    @classmethod
    def must_be_a_branch(cls, value: str) -> str:
        """Reject at the boundary rather than deep in the loop, so a bad key is a
        422 about the request instead of a 500 about a ValueError."""
        try:
            Branch(value)
        except ValueError as exc:
            raise ValueError("option_key must be one of: a, b, c.") from exc
        return value
```

- [ ] **Step 4: Add the endpoint**

Append to `backend/app/main.py`:

```python
@app.post("/rewrite/{session_id}/answer", response_model=RewriteResponse)
async def answer(session_id: str, request: AnswerRequest) -> RewriteResponse:
    """Resume a suspended rewrite. Same three shapes as `/rewrite`, so the front
    end renders a second question exactly as it rendered the first."""
    try:
        outcome = loop.resume(session_id, option_key=request.option_key)
    except loop.UnknownSession as exc:
        raise HTTPException(
            status_code=404,
            detail="No rewrite session with that id — start the rewrite again.",
        ) from exc
    except loop.UnknownDocument as exc:
        # The session outlived its document, which an in-memory store makes
        # possible across a restart. Say which thing is missing.
        raise HTTPException(
            status_code=404,
            detail="The document for this rewrite is gone — upload it again.",
        ) from exc
    except loop.SessionFinished as exc:
        raise HTTPException(
            status_code=409, detail="This rewrite has already finished."
        ) from exc
    except (ModelRefusal, OpenAIError) as exc:
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    return _to_response(outcome)
```

- [ ] **Step 5: Run the whole suite**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `119 passed, 4 skipped`.

- [ ] **Step 6: Check it by hand against the real model**

```bash
cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 3
DOC=$(curl -s -X POST http://localhost:8000/documents \
  -F "file=@sample/meridian-proposal.docx" | python3 -c "import sys,json;print(json.load(sys.stdin)['document_id'])")
SESSION=$(curl -s -X POST http://localhost:8000/rewrite -H "Content-Type: application/json" \
  -d "{\"document_id\":\"$DOC\",\"section_id\":\"s3\",\"instruction\":\"Make this concrete. List the actual deliverables and drop the hedging.\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))")
curl -s -X POST "http://localhost:8000/rewrite/$SESSION/answer" \
  -H "Content-Type: application/json" -d '{"option_key":"a"}' | python3 -m json.tool
```

Expected: a `complete` or `needs_clarification` body, never a 500. Kill the server afterwards.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
Add POST /rewrite/{session_id}/answer

The same three shapes as /rewrite, so a second question renders exactly as the
first did and the front end switches on status alone.

The edge cases are the point of the tests: an unknown session, a session
answered twice by a stale tab (409), a bad option key rejected at the boundary
as a 422 rather than surfacing as a 500, a document lost to a restart while its
session survived — which an in-memory store makes genuinely possible — and a
model failure on a redraft.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: The front end learns the full contract

`lib/api.ts` types only `complete`, and omits `ripples` entirely — so the backend returns them and the browser drops them. Spec §15.10.

**Files:**
- Modify: `frontend/lib/api.ts:36-66`

**Interfaces:**
- Produces: `Ripple`, `Option`, `RewriteComplete`, `RewriteNeedsClarification`, `RewriteDeclined`, `RewriteResult` (the union), `answerQuestion({sessionId, optionKey})`. Tasks 9 and 10 consume these.

- [ ] **Step 1: Replace the types and add the call**

In `frontend/lib/api.ts`, replace everything from the `/**` comment above `RewriteComplete` (line 36) through the end of `rewriteSection` (line 66) with:

```ts
export type Ripple = {
  section_id: string;
  heading: string;
  quote: string;
  kind: string;
  explanation: string;
  proposed_fix: string | null;
  /** False when the quoted clause could not be found where the model said it
   *  was — a possibly invented conflict, shown but never asked about. */
  verified: boolean;
};

export type Option = { key: string; label: string };

/**
 * `status` is the discriminator. All three arms come from both `/rewrite` and
 * `/rewrite/{id}/answer`, so a second question renders exactly like the first.
 */
export type RewriteComplete = {
  status: "complete";
  section_id: string;
  old_text: string;
  new_text: string;
  ripples: Ripple[];
  /** What the agent decided once it had spent its two questions. */
  assumptions: string[];
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

export async function answerQuestion(input: {
  sessionId: string;
  optionKey: string;
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite/${input.sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option_key: input.optionKey }),
    }),
  );
}
```

- [ ] **Step 2: Typecheck — it must fail**

```bash
cd frontend && npx tsc --noEmit
```

Expected: an error in `app/page.tsx` — `result` is now a union and `ResultPanel` takes only `RewriteComplete`. That failure is the point: the type system just found the place the browser was dropping data. Task 10 fixes it.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "$(cat <<'EOF'
Type the whole response contract, not just the happy arm

The API has returned ripples since phase 3 and the front end had no field for
them, so they were parsed and discarded. Hiding part of a document from the
author is the class of bug this tool exists to prevent, and it was happening in
our own client.

Adds the needs_clarification and declined arms and the answer call. Typechecking
now fails in page.tsx, which is correct: that is the place the data was being
dropped.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `QuestionPanel`

The component that renders the interrupt. Its job is to make the quoted clause impossible to miss — a question a consultant skims is a question that gets answered wrongly.

**Files:**
- Create: `frontend/app/components/QuestionPanel.tsx`

**Interfaces:**
- Consumes: `RewriteNeedsClarification` from Task 8.
- Produces: `<QuestionPanel result={...} busy={boolean} onAnswer={(optionKey: string) => void} />`. Task 10 mounts it.

- [ ] **Step 1: Create the component**

Create `frontend/app/components/QuestionPanel.tsx`:

```tsx
"use client";

import type { RewriteNeedsClarification } from "@/lib/api";

/**
 * The interrupt. It exists because the rewrite would otherwise break a promise
 * made elsewhere in the document, and only the author can say which way that
 * should go — so the clause is quoted in full rather than summarised, and the
 * branches are buttons rather than a text box.
 */
export function QuestionPanel({
  result,
  busy,
  onAnswer,
}: {
  result: RewriteNeedsClarification;
  busy: boolean;
  onAnswer: (optionKey: string) => void;
}) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
      <h2 className="font-semibold text-amber-900">One thing before I write it</h2>

      <p className="mt-3 mb-5 text-sm leading-relaxed whitespace-pre-wrap text-slate-800">
        {result.question}
      </p>

      <div className="space-y-2">
        {result.options.map((option) => (
          <button
            key={option.key}
            type="button"
            disabled={busy}
            onClick={() => onAnswer(option.key)}
            className="flex w-full items-start gap-3 rounded-md border
                       border-amber-300 bg-white p-3 text-left text-sm
                       hover:border-amber-500 hover:bg-amber-100
                       disabled:opacity-50"
          >
            <span className="font-semibold text-amber-800 uppercase">
              {option.key}
            </span>
            <span className="text-slate-700">{option.label}</span>
          </button>
        ))}
      </div>

      {busy && (
        <p className="mt-4 text-xs text-amber-800">Applying your answer…</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: still the `page.tsx` error from Task 8, and **no new errors in `QuestionPanel.tsx`**.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/QuestionPanel.tsx
git commit -m "$(cat <<'EOF'
Render the question

The clause is quoted in full rather than summarised, and the branches are
buttons rather than a text box: a question a consultant skims is a question that
gets answered wrongly, and an open prompt hands the judgement straight back to
the human the agent was supposed to be helping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Render everything the backend returns

Ripples, assumptions, the declined case, and the wiring that posts an answer. After this task nothing the API returns is dropped.

**Files:**
- Modify: `frontend/app/components/ResultPanel.tsx`
- Modify: `frontend/app/page.tsx:21-39` (the handler), `:100-105` (the render)

**Interfaces:**
- Consumes: everything from Tasks 8 and 9.

- [ ] **Step 1: Rewrite `ResultPanel`**

Replace `frontend/app/components/ResultPanel.tsx` entirely:

```tsx
"use client";

import type { RewriteComplete, Ripple } from "@/lib/api";

/**
 * A consequence the agent judged not worth interrupting for. Shown, never
 * applied: nothing is written outside the selected section, so the author stays
 * the editor of record.
 */
function RippleCard({ ripple }: { ripple: Ripple }) {
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">
          {ripple.heading}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
          {ripple.kind.replace(/_/g, " ")}
        </span>
        {!ripple.verified && (
          // The quote could not be found where the model said it was, so the
          // conflict may not exist. Shown rather than hidden, but labelled.
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
            unverified
          </span>
        )}
      </div>

      <p className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-600 italic">
        “{ripple.quote}”
      </p>
      <p className="mt-2 text-sm text-slate-600">{ripple.explanation}</p>
      {ripple.proposed_fix && (
        <p className="mt-2 text-sm text-emerald-800">
          <span className="font-medium">Suggested:</span> {ripple.proposed_fix}
        </p>
      )}
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

      {/* What the agent decided instead of asking a third time. Stated up front,
          because an assumption the author has to go looking for is a silent one. */}
      {result.assumptions.length > 0 && (
        <section className="rounded-md border border-slate-300 bg-slate-50 p-3">
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Assumed, without asking again
          </h3>
          <ul className="mt-2 space-y-1">
            {result.assumptions.map((assumption) => (
              <li key={assumption} className="text-sm text-slate-700">
                {assumption}
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.ripples.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Also affected — {result.ripples.length}, not applied
          </h3>
          <p className="mt-1 mb-3 text-xs text-slate-500">
            Nothing outside the section you picked has been changed.
          </p>
          <ul className="space-y-2">
            {result.ripples.map((ripple, index) => (
              <RippleCard key={`${ripple.section_id}-${index}`} ripple={ripple} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire up `page.tsx`**

In `frontend/app/page.tsx`, replace the import line (line 8) with:

```tsx
import { QuestionPanel } from "./components/QuestionPanel";
import {
  answerQuestion,
  rewriteSection,
  type RewriteResult,
  type UploadResponse,
} from "@/lib/api";
```

Replace `handleInstruction` (lines 21-39) with:

```tsx
  async function run(call: () => Promise<RewriteResult>) {
    setBusy(true);
    setError(null);
    try {
      setResult(await call());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rewrite failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleInstruction(instruction: string) {
    if (!document || !selectedId) return;
    setResult(null);
    await run(() =>
      rewriteSection({
        documentId: document.document_id,
        sectionId: selectedId,
        instruction,
      }),
    );
  }

  // The answer replaces the question in place, so a second question renders
  // exactly where the first one was rather than stacking below it.
  async function handleAnswer(sessionId: string, optionKey: string) {
    await run(() => answerQuestion({ sessionId, optionKey }));
  }
```

Replace the render line (line 104) with:

```tsx
          {result?.status === "needs_clarification" && (
            <QuestionPanel
              result={result}
              busy={busy}
              onAnswer={(optionKey) =>
                handleAnswer(result.session_id, optionKey)
              }
            />
          )}

          {/* Declining is a result, not an error: the instruction did not fit
              the section, and saying so beats mangling it confidently. */}
          {result?.status === "declined" && (
            <div className="rounded-lg border border-slate-300 bg-white p-6">
              <h2 className="font-semibold">Not rewritten</h2>
              <p className="mt-2 text-sm text-slate-600">{result.reason}</p>
            </div>
          )}

          {result?.status === "complete" && <ResultPanel result={result} />}
```

- [ ] **Step 3: Typecheck — it must now pass**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output. The `page.tsx` error introduced in Task 8 is resolved by handling all three arms.

- [ ] **Step 4: Check it in the browser**

Two terminals:

```bash
cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload
cd frontend && npm run dev
```

At http://localhost:3000, upload `backend/sample/meridian-proposal.docx`, pick **2. Scope of Work** (it is `s3` — the sample's title line takes `s1` as an untitled opening), and enter *"Make this concrete. List the actual deliverables and drop the hedging."*

Confirm: the question renders with three lettered buttons; clicking one disables them and produces either a result or a second question; ripples appear under the before/after with their quotes.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/components/ResultPanel.tsx frontend/app/page.tsx
git commit -m "$(cat <<'EOF'
Render every outcome, and stop dropping ripples

The front end assumed every rewrite completes. It now renders the question, the
declined case — a result rather than an error — and the ripples and assumptions
it had been parsing and discarding.

Ripples carry their quote, their proposed fix and, where the model's quote could
not be found in the document, an "unverified" label. Showing an ungrounded
finding without saying it is ungrounded would be its own kind of lie, and hiding
it would be the bug this tool exists to prevent.

The panel says out loud that nothing outside the selected section was changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: A live case, and honest docs

One opt-in calibration case that the loop terminates, and the reviewer-facing documents brought up to date.

**Files:**
- Modify: `backend/tests/test_calibration.py`, `README.md`, `docs/status.md`

- [ ] **Step 1: Add the live loop case**

The file's module-level `pytestmark` already skips everything unless `RUN_LIVE_TESTS=1`, and its `sections` fixture and `id_of()` helper (lines 33-48) already handle the sample document and the positional-id trap. Reuse both — do not address sections by literal id.

Add these two imports at the top of `backend/tests/test_calibration.py`:

```python
from app import loop, store
from app.parsing import ParsedDocument, parse_docx
```

(`parse_docx` is already imported; extend that line rather than duplicating it.)

Then append:

```python
def test_the_loop_terminates_within_two_questions(sections):
    """Against the real model, on the real document.

    Asserts only that the loop ends — never on wording, and never on which
    branch the model's audit provokes. Temperature 0 is not bit-deterministic on
    this deployment, so a golden output would be a flaky test wearing a
    confident face.

    Branch (a) is chosen every round because it is the only one that re-drafts,
    so it is the only path that can produce a second, genuinely new question.
    """
    document_id = store.save_document(
        ParsedDocument(sections=sections, headings_detected=True)
    )
    outcome = loop.start(
        document_id,
        section_id=id_of(sections, "Scope of Work"),
        instruction="Make this concrete. List the actual deliverables and drop "
        "the hedging.",
    )

    rounds = 0
    while isinstance(outcome, loop.Asking):
        rounds += 1
        assert rounds <= 2, "the two-question cap did not hold"
        outcome = loop.resume(outcome.session_id, option_key="a")

    assert isinstance(outcome, (loop.Completed, loop.Declined))
```

- [ ] **Step 2: Run it against the real model**

```bash
cd backend && RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

Expected: 5 passed. Costs real tokens and about 30 seconds.

- [ ] **Step 3: Run the offline suite one more time**

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Expected: `119 passed, 5 skipped`.

- [ ] **Step 4: Update `docs/status.md`**

- Mark phase 4 **done** and phase 5 **next** in the table at the top.
- Update the test counts in "Where we are" and "How to test" to the real numbers from Step 3.
- Add `loop.py` to the "What exists" file listing: *"The suspendable run. Which branch re-drafts, when to audit again, when to stop asking."*
- Remove the two resolved entries from "Known gaps": the front end assuming every rewrite completes, and the README not explaining the interrupt policy if Step 5 covers it.
- Add to "Verified, not assumed" whatever the live run in Step 2 actually showed — how many rounds it took, and which branch produced a second question. Write what happened, not what was hoped for.

- [ ] **Step 5: Update `README.md`**

- Change the status line to phases 0–4 of 5 complete.
- Add the three branches and what each does to the "How it decides to interrupt you" section — that is the part a reviewer reads first.
- Add to "Decisions worth knowing": **only one branch of three returns to the model**, and why.
- Update the test count.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_calibration.py README.md docs/status.md
git commit -m "$(cat <<'EOF'
Phase 4: the clarification loop closes

One opt-in live case asserting the loop terminates within two questions, against
the real model on the real document. It asserts on termination alone — never on
wording, never on which branch the audit provokes. Temperature 0 is not
bit-deterministic on this deployment, so a golden output would be a flaky test
wearing a confident face.

README and status notes brought up to date, including what the live run actually
did rather than what it was hoped to do.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

**Spec coverage.** Every §15 subsection maps to a task: §15.1 → 5, §15.2 → 1, §15.3 → 3 and 5, §15.4 → 5 and 6, §15.5 → 6, §15.6 → 6 and 10, §15.7 → 5 (the comment in the `HOLD` branch), §15.8 → 4, §15.9 → 7, §15.10 → 2 (guard), 8 and 10 (ripples), 1 (instruction), §15.11 → tests throughout, §15.12 → the task order.

**Type consistency.** `decide(..., rewritten_section_id=...)` is defined in Task 2 and used in Tasks 2, 4 and 5. `to_ripple` is renamed in Task 2 and used in Tasks 2, 5 and 6. `Branch` is defined in Task 1 and used in Tasks 5 and 7. `hold_constraint` and `assumption_for` are defined in Tasks 5 and 6 and used only in `loop.py`. `Completed.assumptions` is declared in Task 4, populated in Task 6, exposed in Task 7 and rendered in Task 10.

**One deliberate ordering choice.** Task 8 leaves the front end failing its typecheck, and Task 10 fixes it. That is intentional: the compile error is what proves the data was being dropped, and closing the gap in a single task would hide it.

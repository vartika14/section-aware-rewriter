# Mark Complete & Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the author rewrite several sections in one session, accept the ones
they want, and download a real `.docx` with those edits applied — while later
rewrites correctly see earlier accepted edits, not the stale upload original.

**Architecture:** The frontend accumulates `{section_id: text}` as the author
accepts rewrites and sends it with every `/rewrite` call. The backend overlays
it onto the stored document before DRAFT/DETECT run, then freezes that overlaid
view into the session the moment a question is asked, so answering it never
sees a state that shifted underneath it. A new small module inverts parsing.py
to turn sections back into a `.docx`; one new endpoint serves it.

**Tech Stack:** Unchanged — Python 3.12, FastAPI, Pydantic v2, pytest,
`python-docx` (already a dependency), Next.js, TypeScript, Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-17-export-flow-design.md` — this plan
implements every numbered section of it.

## Global Constraints

- **No new dependencies.** `python-docx` is already in `requirements.txt` and
  already used both for parsing and for the sample-document scripts.
- **`current_texts` is optional everywhere it's introduced**, defaulting to "no
  override." Every test that exists before this plan starts must keep passing
  unchanged — this is additive, not a redesign.
- **Offline by default.** The model seam is substituted the same way it already
  is throughout the suite; export itself makes no model call at all.
- **No new frontend automated tests** — consistent with the standing project
  decision (frontend verified by `tsc` and a manual click-through), stated once
  in the simplified agent spec.
- **Commit after every task.** End every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/export.py` | `build_docx()` — sections back into `.docx` bytes. The inverse of `parsing.py`. |
| `backend/tests/test_export.py` | Round-trip tests: build, re-parse, confirm nothing was lost. |
| `frontend/app/components/ExportPanel.tsx` | The "Mark complete & download" control — its own busy/error state, separate from a rewrite's. |

**Modified:**

| File | Change |
|---|---|
| `backend/app/rewrite.py` | `overlay_texts()` — the one function both the rewrite path and the export path share. |
| `backend/app/store.py` | `RewriteSession` gains `context: list[Section]`. |
| `backend/app/orchestrator.py` | `start()` takes `current_texts`; `resume()` reasons against `session.context`, not a fresh document fetch. |
| `backend/app/main.py` | `RewriteRequest` gains `current_texts`; new `POST /documents/{id}/export`. |
| `backend/tests/test_rewrite.py`, `test_orchestrator.py`, `test_api.py` | New tests per task below. |
| `frontend/lib/api.ts` | `rewriteSection()` sends `currentTexts`; new `exportDocument()`. |
| `frontend/app/components/ResultPanel.tsx` | "Accept into final document" button. |
| `frontend/app/components/SectionList.tsx` | A marker for sections with an accepted edit. |
| `frontend/app/page.tsx` | `currentTexts` state, accept handler, mounts `ExportPanel`. |

---

## Task 1: `overlay_texts()` in `rewrite.py`

**Files:**
- Modify: `backend/app/rewrite.py`
- Modify: `backend/tests/test_rewrite.py`

**Interfaces:**
- Produces: `def overlay_texts(sections: list[Section], current_texts: dict[str, str]) -> list[Section]`.
  Task 2 (`orchestrator.start`) and Task 5 (the export endpoint) both call this —
  it is the one place "apply accepted edits to a section list" is implemented.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_rewrite.py` (its existing `SECTIONS` fixture —
`s1`/`s2`/`s3` — is reused unchanged):

```python
from app.rewrite import overlay_texts  # add to the existing import line


# --- overlay_texts() -------------------------------------------------------


def test_overlay_texts_replaces_matching_ids():
    overlaid = overlay_texts(SECTIONS, {"s2": "A new, more concrete scope."})

    assert [s.text for s in overlaid] == [
        "Act on it this quarter.",
        "A new, more concrete scope.",
        "A fixed fee of EUR 48,000.",
    ]


def test_overlay_texts_leaves_ids_headings_and_order_untouched():
    overlaid = overlay_texts(SECTIONS, {"s2": "A new, more concrete scope."})

    assert [s.id for s in overlaid] == [s.id for s in SECTIONS]
    assert [s.heading for s in overlaid] == [s.heading for s in SECTIONS]


def test_overlay_texts_with_an_empty_map_changes_nothing():
    assert overlay_texts(SECTIONS, {}) == SECTIONS


def test_overlay_texts_ignores_an_id_that_matches_no_section():
    """A stale id from a tab that hasn't refreshed since a new upload must not
    raise — it just has nothing to attach to."""
    assert overlay_texts(SECTIONS, {"s99": "orphaned"}) == SECTIONS
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

Expected: `ImportError: cannot import name 'overlay_texts'`.

- [ ] **Step 3: Implement it**

Append to `backend/app/rewrite.py`, after `find_section`:

```python
def overlay_texts(sections: list[Section], current_texts: dict[str, str]) -> list[Section]:
    """Replace each section's text with the author's current accepted version,
    where one exists. Ids, headings and order are untouched — only what the
    rest of the pipeline reads as "the document" changes.

    Shared by the rewrite path (orchestrator.start) and the export path (the
    /documents/{id}/export endpoint) — one function, so "apply what the author
    has accepted so far" means the same thing in both places.
    """
    return [
        s.model_copy(update={"text": current_texts[s.id]}) if s.id in current_texts else s
        for s in sections
    ]
```

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rewrite.py backend/tests/test_rewrite.py
git commit -m "$(cat <<'EOF'
Add overlay_texts() — apply accepted edits to a section list

One function, shared by the rewrite path and the export path: replace a
section's text with the author's current accepted version where one exists,
leave ids/headings/order untouched otherwise. An unknown id is ignored rather
than raising — a stale tab sending a section id from before a new upload must
not crash the request.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `store.py` + `orchestrator.start()` — the override reaches DRAFT/DETECT

**Files:**
- Modify: `backend/app/store.py`
- Modify: `backend/app/orchestrator.py`
- Modify: `backend/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `overlay_texts` from Task 1.
- Produces: `store.RewriteSession.context: list[Section]` (new field, required — every
  session now carries the overlaid view it was created under).
- Produces: `orchestrator.start(document_id, *, section_id, instruction, current_texts: dict[str, str] | None = None) -> Outcome`.
  Task 3 (`resume`) reads `session.context`. Task 6 (`main.py`) passes
  `current_texts` through from the request.

- [ ] **Step 1: Write the failing tests**

Insert into `backend/tests/test_orchestrator.py`, directly after
`test_an_unknown_section_is_not_a_crash` and before the
`from app.question import Branch` line (these are `start()`-only tests, so
they belong with the others that only need `document_id`/`model`):

```python
def test_current_texts_reach_the_draft_prompt(document_id, model, monkeypatch):
    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text="drafted")

    monkeypatch.setattr("app.rewrite.structured_completion", draft)

    orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000, renegotiated."},
    )

    assert "A fixed fee of EUR 90,000, renegotiated." in captured["user"]
    assert "A fixed fee of EUR 48,000 covers it." not in captured["user"]


def test_current_texts_reach_the_detect_prompt(document_id, model, monkeypatch):
    captured = {}

    def detect(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](findings=[])

    monkeypatch.setattr("app.conflicts.structured_completion", detect)

    orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000, renegotiated."},
    )

    assert "A fixed fee of EUR 90,000, renegotiated." in captured["user"]


def test_no_current_texts_behaves_exactly_as_before(document_id, model):
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")

    assert isinstance(outcome, orchestrator.Completed)


def test_the_suspended_session_stores_the_overlaid_context(document_id, model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 90,000.",
                 explanation="test", blocking=True)
    ]

    outcome = orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000."},
    )

    assert isinstance(outcome, orchestrator.Asking)
    stored = {s.id: s.text for s in store.get_session(outcome.session_id).context}
    assert stored["s4"] == "A fixed fee of EUR 90,000."
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: `TypeError: start() got an unexpected keyword argument 'current_texts'`.

- [ ] **Step 3: Add the field to `RewriteSession`**

In `backend/app/store.py`, add `Section` to the existing import and the new
field:

```python
from .conflicts import Conflict, Note
from .parsing import ParsedDocument, Section
```

```python
class RewriteSession(BaseModel):
    """A rewrite that stopped to ask one question, and everything needed to
    finish it.

    `context` is the overlaid sections view — the document as the author
    currently had it, accepted edits included — at the moment the question was
    asked. `resume()` reasons against this, never against a fresh re-overlay,
    so an answer is always checked against exactly the document the question
    was asked about.

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
    context: list[Section]
    asking: list[Conflict]
    notes: list[Note]
    resolved: bool = False
```

- [ ] **Step 4: Thread the override through `start()`**

In `backend/app/orchestrator.py`, add `overlay_texts` to the existing import
from `.rewrite`, then replace `start()`:

```python
from .rewrite import draft_section, find_section, overlay_texts
```

```python
def start(
    document_id: str, *, section_id: str, instruction: str,
    current_texts: dict[str, str] | None = None,
) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    sections = overlay_texts(document.sections, current_texts or {})

    try:
        section = find_section(sections, section_id)
    except KeyError as exc:
        raise UnknownSection(section_id) from exc

    draft = draft_section(sections=sections, section_id=section_id, instruction=instruction)

    if not draft.applicable:
        return Declined(
            section_id=section.id,
            reason=draft.inapplicable_reason or "That instruction does not apply to this section.",
        )

    conflicts = find_conflicts(
        sections=sections, section_id=section_id,
        instruction=instruction, new_text=draft.new_text,
    )
    decision = decide(conflicts, sections, rewritten_id=section_id)

    if decision.action == "complete":
        return Completed(
            section_id=section.id, old_text=section.text,
            new_text=draft.new_text, notes=decision.notes,
        )

    heading = find_section(sections, decision.asking[0].section_id).heading
    question = compose_question(
        decision.asking, heading=heading, sections=sections, instruction=instruction
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id=section_id, instruction=instruction,
            draft_text=draft.new_text, context=sections,
            asking=decision.asking, notes=decision.notes,
        )
    )
    return Asking(session_id=session_id, section_id=section.id, question=question)
```

Every use of `document.sections` in the old body becomes `sections` (the
overlaid list); `document` itself is now only used for the initial
`UnknownDocument` check. `section.text` used for `old_text` therefore reflects
the author's *current* accepted text, not necessarily the pristine upload —
correct, since "before" should mean "before this rewrite."

- [ ] **Step 5: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: all pass. (`resume()` will fail to construct a `RewriteSession` at
this point wherever it's exercised via `start()`, since `context` has no
default — that's expected and fixed in Task 3, which runs immediately after.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/app/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
start() takes current_texts; RewriteSession freezes the overlaid context

An accepted edit to one section now reaches DRAFT and DETECT when a later
section is rewritten — checking a fee section against a scope that's already
been superseded is the same silent-inconsistency failure this whole app exists
to catch, one level up.

RewriteSession.context stores the overlaid view at the moment a question is
asked, not just document_id — resume() (next commit) reads this instead of
re-fetching and re-overlaying, so an answer is always checked against exactly
the document the question was asked about, not a state that could have shifted
since.

current_texts defaults to None/{} everywhere, so every call site that doesn't
pass it behaves exactly as before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `resume()` reasons against the frozen context

**Files:**
- Modify: `backend/app/orchestrator.py`
- Modify: `backend/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `RewriteSession.context` from Task 2.
- Produces: `resume()` — same signature as before, behaviour changed internally.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_orchestrator.py`, near the other `resume()`
tests:

```python
def test_resume_reasons_against_the_frozen_context_not_the_live_document(
    document_id, model, monkeypatch
):
    """The session's context is what was true when the question was asked. A
    change to the underlying document afterward must not leak into resume() —
    there is no mechanism for one here (documents are never mutated), but the
    session must not silently re-derive from document.sections either."""
    frozen_context = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s4", heading="4. Fees and Payment",
                text="A fixed fee of EUR 999,000, frozen at ask time."),
    ]
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id="s2", instruction="Be concrete.",
            draft_text="drafted", context=frozen_context,
            asking=[Conflict(section_id="s4", quote="A fixed fee of EUR 999,000, frozen at ask time.",
                              explanation="test", blocking=True)],
            notes=[],
        )
    )

    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text="second draft")

    monkeypatch.setattr("app.rewrite.structured_completion", draft)

    orchestrator.resume(session_id, option_key="a")

    assert "A fixed fee of EUR 999,000, frozen at ask time." in captured["user"]
    assert "A fixed fee of EUR 48,000 covers it." not in captured["user"]
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py::test_resume_reasons_against_the_frozen_context_not_the_live_document -q
```

Expected: fails — `resume()` still reads `document.sections`, so the real
document's fee text (`"A fixed fee of EUR 48,000 covers it."`) leaks into the
prompt instead of the frozen one.

- [ ] **Step 3: Update `resume()`**

Replace the body of `resume()` in `backend/app/orchestrator.py`:

```python
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

    # Still the correctness check that the document itself wasn't lost to a
    # restart. Its .sections are no longer what DRAFT/DETECT reason against —
    # session.context is — but this existence check stays.
    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # ValueError on anything else, by design
    by_id = {s.id: s for s in session.context}
    heading = by_id[session.asking[0].section_id].heading

    if branch is Branch.HOLD:
        draft = draft_section(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction,
            constraints=[hold_constraint(session.asking, heading)],
        )
        found = find_conflicts(
            sections=session.context, section_id=session.section_id,
            instruction=session.instruction, new_text=draft.new_text,
        )
        grounded = ground(found, by_id, rewritten_id=session.section_id)
        notes = session.notes + to_notes(found, grounded, by_id)
        new_text = draft.new_text
    else:
        new_text = session.draft_text
        notes = session.notes + (
            to_notes(session.asking, session.asking, by_id) if branch is Branch.FLAG else []
        )

    session.resolved = True
    section = find_section(session.context, session.section_id)
    return Completed(section_id=section.id, old_text=section.text, new_text=new_text, notes=notes)
```

Every `document.sections` becomes `session.context`; the `document` lookup
itself stays, doing only the existence check it always did.

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected: all pass, including every pre-existing `resume()` test — they
already go through `start()` first, which now always populates `context`, so
they exercise the new path without needing changes themselves.

- [ ] **Step 5: Run the whole backend suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: passes except `test_api.py`, which still constructs sessions the old
way in spirit — actually it doesn't construct `RewriteSession` directly at
all, so this should already be green. If anything unrelated fails, stop and
find out why before continuing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
resume() reasons against the frozen session context

Every use of document.sections inside resume() becomes session.context. The
document lookup itself stays — it is still how an answer to a session whose
document was lost to a restart gets a clean 404 — but its .sections are no
longer what a HOLD redraft or re-check is measured against.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `app/export.py` — sections back into a `.docx`

**Files:**
- Create: `backend/app/export.py`
- Create: `backend/tests/test_export.py`

**Interfaces:**
- Produces: `def build_docx(sections: list[Section]) -> bytes`. Task 5 (the
  export endpoint) is its only caller.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export.py`:

```python
"""Tests for turning sections back into a .docx — the inverse of parsing.py.

Round-trips through parse_docx() rather than asserting on python-docx
internals: the only thing that matters is that a document built here parses
back into the same sections a moment later.
"""

from app.export import build_docx
from app.parsing import Section, parse_docx


def test_a_single_section_round_trips():
    sections = [Section(id="s1", heading="1. Scope", text="The engagement is advisory.")]

    reparsed = parse_docx(build_docx(sections))

    assert [s.heading for s in reparsed.sections] == ["1. Scope"]
    assert reparsed.sections[0].text == "The engagement is advisory."


def test_multiple_sections_round_trip_in_order():
    sections = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000."),
    ]

    reparsed = parse_docx(build_docx(sections))

    assert [s.heading for s in reparsed.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]
    assert [s.text for s in reparsed.sections] == [s.text for s in sections]


def test_a_multi_paragraph_section_round_trips():
    sections = [Section(id="s1", heading="1. Scope", text="First paragraph.\n\nSecond paragraph.")]

    reparsed = parse_docx(build_docx(sections))

    assert reparsed.sections[0].text == "First paragraph.\n\nSecond paragraph."


def test_a_preamble_round_trips_without_a_heading_style():
    sections = [
        Section(id="preamble", heading="(untitled opening)", text="Proposal: Example."),
        Section(id="s1", heading="1. Scope", text="The engagement is advisory."),
    ]

    reparsed = parse_docx(build_docx(sections))

    assert reparsed.sections[0].id == "preamble"
    assert "Proposal: Example." in reparsed.sections[0].text
    assert reparsed.sections[1].heading == "1. Scope"
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_export.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.export'`.

- [ ] **Step 3: Create `export.py`**

```python
"""Turn sections back into a .docx — the inverse of parsing.py.

Same shape the sample-document scripts already use: a plain paragraph for a
preamble (no heading style, so it re-parses as a preamble again on the way
back in), Heading 1 + body paragraphs for everything else, in the order given.
"""

from io import BytesIO

from docx import Document

from .parsing import PREAMBLE_HEADING, Section


def build_docx(sections: list[Section]) -> bytes:
    document = Document()

    for section in sections:
        if section.heading != PREAMBLE_HEADING:
            document.add_paragraph(section.heading, style="Heading 1")
        for paragraph in section.text.split("\n\n"):
            document.add_paragraph(paragraph)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_export.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "$(cat <<'EOF'
Add export.py: sections back into a .docx

The inverse of parsing.py, using the exact same shape the sample-document
scripts already generate — a plain paragraph for a preamble, Heading 1 + body
paragraphs for everything else. Tested by round-tripping through parse_docx()
rather than asserting on python-docx internals.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `POST /documents/{document_id}/export`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `build_docx` (Task 4), `overlay_texts` (Task 1).
- Produces: `POST /documents/{document_id}/export`, body
  `{"sections": [{"id": str, "text": str}]}`, response: raw `.docx` bytes.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
# --- export ----------------------------------------------------------------


def export(document_id: str, sections: list[dict]):
    return client.post(f"/documents/{document_id}/export", json={"sections": sections})


def test_export_returns_a_docx_with_the_submitted_text(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    reparsed = parse_docx(response.content)
    scope = next(s for s in reparsed.sections if s.heading == "2. Scope of Work")
    assert scope.text == "A new, concrete scope."


def test_export_falls_back_to_the_original_text_for_a_section_not_submitted(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    reparsed = parse_docx(response.content)
    fees = next(s for s in reparsed.sections if s.heading == "3. Fees")
    assert fees.text == PROPOSAL[5][1]


def test_export_ignores_a_section_id_the_document_does_not_have(document_id):
    response = export(document_id, [{"id": "s99", "text": "orphaned"}])

    assert response.status_code == 200


def test_export_preserves_the_documents_original_order(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [])

    reparsed = parse_docx(response.content)
    assert [s.heading for s in reparsed.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]


def test_export_404s_on_an_unknown_document():
    response = export("nope", [])

    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_api.py -k export -q
```

Expected: mostly `404`s from FastAPI's own unmatched-route handling, which
looks similar to the real thing but isn't — `test_export_404s_on_an_unknown_document`
specifically still fails, because FastAPI's generic 404 body is
`{"detail": "Not Found"}`, and `"document"` is not a substring of `"not
found"`. That's the tell that this is the wrong 404, not the right one.

- [ ] **Step 3: Add the endpoint**

In `backend/app/main.py`, add `Response` to the `fastapi` import and add two
new imports:

```python
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
```

```python
from .export import build_docx
from .rewrite import overlay_texts
```

Append near the bottom of the file, after the `answer` endpoint:

```python
class SectionText(BaseModel):
    id: str
    text: str


class ExportRequest(BaseModel):
    sections: list[SectionText]


@app.post("/documents/{document_id}/export")
async def export_document(document_id: str, request: ExportRequest) -> Response:
    """Assemble the current state of the document into a .docx.

    Order and headings always come from the backend's own stored document,
    never from the request — the request supplies text only, via the same
    overlay_texts() the rewrite path uses. A section id the request is missing
    falls back to the original text rather than being dropped; an id the
    request has that the document doesn't recognise is ignored.
    """
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        )

    submitted = {s.id: s.text for s in request.sections}
    sections = overlay_texts(document.sections, submitted)

    return Response(
        content=build_docx(sections),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="rewritten-document.docx"'},
    )
```

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: all pass, existing tests unaffected.

- [ ] **Step 5: Run the whole backend suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
Add POST /documents/{id}/export

Reuses overlay_texts() from the rewrite path rather than reimplementing
"apply submitted text over the stored original" a second time — the same
function now backs both "what does DRAFT/DETECT see" and "what goes in the
downloaded file."

Order and headings are never taken from the request, only text — a defensive
choice so a partial or buggy client payload can drop nothing and corrupt
nothing about the document's structure.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `POST /rewrite` accepts `current_texts`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `RewriteRequest.current_texts: dict[str, str] = {}`, threaded into
  `orchestrator.start(..., current_texts=request.current_texts)`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py`, extend the `rewrite()` helper to optionally
pass `current_texts`:

```python
def rewrite(
    document_id: str, section_id: str = "s2", instruction: str = "Be concrete.",
    current_texts: dict | None = None,
):
    body = {"document_id": document_id, "section_id": section_id, "instruction": instruction}
    if current_texts is not None:
        body["current_texts"] = current_texts
    return client.post("/rewrite", json=body)
```

Then append:

```python
def test_current_texts_reach_the_draft_prompt(document_id, monkeypatch):
    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text=NEW_TEXT)

    monkeypatch.setattr("app.rewrite.structured_completion", draft)
    monkeypatch.setattr(
        "app.conflicts.structured_completion", lambda **kw: kw["schema"](findings=[])
    )

    rewrite(
        document_id, section_id="s2",
        current_texts={"s3": "A renegotiated fee of EUR 90,000."},
    )

    assert "A renegotiated fee of EUR 90,000." in captured["user"]


def test_no_current_texts_still_works(document_id, fake_model):
    response = rewrite(document_id)

    assert response.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/bin/python -m pytest tests/test_api.py -k current_texts -q
```

Expected: `test_current_texts_reach_the_draft_prompt` fails with an
`AssertionError`, not a `422`. None of the models in `main.py` set
`extra="forbid"`, so a `current_texts` key in the request body is currently
just silently ignored by Pydantic rather than rejected — the request succeeds,
`orchestrator.start()` runs without an override, and the renegotiated fee text
never reaches the captured prompt. `test_no_current_texts_still_works` already
passes, since it doesn't depend on the new field at all.

- [ ] **Step 3: Add the field**

In `backend/app/main.py`, add the field to `RewriteRequest`:

```python
class RewriteRequest(BaseModel):
    document_id: str
    section_id: str
    instruction: str
    current_texts: dict[str, str] = {}

    @field_validator("instruction")
    @classmethod
    def instruction_must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Instruction must not be empty.")
        return value.strip()
```

And pass it through in the `rewrite` endpoint:

```python
    try:
        outcome = orchestrator.start(
            request.document_id,
            section_id=request.section_id,
            instruction=request.instruction,
            current_texts=request.current_texts,
        )
```

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: all pass.

- [ ] **Step 5: Run the whole backend suite one more time**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Expected: same count as before this plan started, plus every test added in
Tasks 1–6.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
POST /rewrite accepts current_texts

Defaults to {}, so every existing caller behaves exactly as before. The
backend half of the loop is now complete: accept an edit, rewrite another
section, and the second rewrite's conflict check sees the first one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `lib/api.ts` — the frontend contract

**Files:**
- Modify: `frontend/lib/api.ts`

**Interfaces:**
- Produces: `rewriteSection()` gains an optional `currentTexts` input, sent as
  `current_texts`. New `exportDocument(input: {documentId: string; sections: Record<string, string>}): Promise<Blob>`.
  Task 10 (`ExportPanel.tsx`) is its only caller.

- [ ] **Step 1: Edit the file**

Replace `rewriteSection` and append `exportDocument`:

```ts
export async function rewriteSection(input: {
  documentId: string;
  sectionId: string;
  instruction: string;
  currentTexts?: Record<string, string>;
}): Promise<RewriteResult> {
  return unwrap<RewriteResult>(
    await fetch(`${API_BASE}/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: input.documentId,
        section_id: input.sectionId,
        instruction: input.instruction,
        current_texts: input.currentTexts ?? {},
      }),
    }),
  );
}

/**
 * Returns the .docx as a Blob, ready for the browser's download mechanism.
 * This endpoint returns a file, not JSON, so it doesn't go through unwrap().
 */
export async function exportDocument(input: {
  documentId: string;
  sections: Record<string, string>;
}): Promise<Blob> {
  const response = await fetch(`${API_BASE}/documents/${input.documentId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sections: Object.entries(input.sections).map(([id, text]) => ({ id, text })),
    }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Export failed (${response.status})`);
  }

  return response.blob();
}
```

`answerQuestion()` is unchanged — per the spec, a suspended question's context
is frozen server-side, so the answer request has no `current_texts` to send.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean — nothing yet calls `exportDocument`, and `rewriteSection`'s
new parameter is optional, so `page.tsx`'s existing call site still compiles.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "$(cat <<'EOF'
lib/api.ts: current_texts on rewriteSection, add exportDocument()

exportDocument() returns a Blob rather than going through unwrap() — this
endpoint answers with a file, not JSON. answerQuestion() is untouched: a
suspended question's context is frozen server-side, so there is nothing for
the answer request to override.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `ResultPanel.tsx` — Accept into final document

**Files:**
- Modify: `frontend/app/components/ResultPanel.tsx`

**Interfaces:**
- Produces: `ResultPanel` gains two props: `onAccept: () => void`,
  `accepted: boolean`. Task 10 (`page.tsx`) supplies both.

- [ ] **Step 1: Edit the component**

Replace the file's header (`NoteCard` is unchanged, only `ResultPanel` itself
changes):

```tsx
export function ResultPanel({
  result,
  onAccept,
  accepted,
}: {
  result: RewriteComplete;
  onAccept: () => void;
  accepted: boolean;
}) {
  return (
    <div className="space-y-6 rounded-lg border border-slate-300 bg-white p-6">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">4. Result</h2>
          <button
            type="button"
            onClick={onAccept}
            disabled={accepted}
            className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium
                       text-white hover:bg-emerald-800 disabled:bg-slate-300"
          >
            {accepted ? "Accepted" : "Accept into final document"}
          </button>
        </div>
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

Expected: an error at `page.tsx`'s `<ResultPanel result={result} />` call
site — it's now missing two required props. That's correct; Task 10 supplies
them. No other file should error.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/ResultPanel.tsx
git commit -m "$(cat <<'EOF'
ResultPanel: an explicit Accept button

Nothing is accepted implicitly — clicking Accept is the only thing that
commits a rewrite into the tracked document state, so re-running a rewrite you
don't like never silently overwrites one you already accepted.

page.tsx does not yet supply the new props — fixed in a later commit in this
same task sequence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `SectionList.tsx` — mark edited sections

**Files:**
- Modify: `frontend/app/components/SectionList.tsx`

**Interfaces:**
- Produces: `SectionList` gains a required prop `editedIds: Set<string>`.
  Task 10 (`page.tsx`) computes and supplies it.

- [ ] **Step 1: Edit the component**

```tsx
"use client";

import type { Section } from "@/lib/api";

export function SectionList({
  sections,
  headingsDetected,
  selectedId,
  editedIds,
  onSelect,
}: {
  sections: Section[];
  headingsDetected: boolean;
  selectedId: string | null;
  editedIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
      <h2 className="mb-1 font-semibold">2. Pick a section</h2>
      <p className="mb-4 text-sm text-slate-500">
        {sections.length} section{sections.length === 1 ? "" : "s"} found.
        {editedIds.size > 0 &&
          ` ${editedIds.size} edited.`}
      </p>

      {!headingsDetected && (
        <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          No heading styles found in this document, so these boundaries are a
          guess based on blank lines. Check them before relying on a rewrite.
        </p>
      )}

      <ul className="space-y-2">
        {sections.map((section) => (
          <li key={section.id}>
            <label
              className={`flex cursor-pointer gap-3 rounded-md border p-3 ${
                selectedId === section.id
                  ? "border-slate-800 bg-slate-50"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <input
                type="radio"
                name="section"
                className="mt-1"
                checked={selectedId === section.id}
                onChange={() => onSelect(section.id)}
              />
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 font-medium">
                  {section.heading}
                  {editedIds.has(section.id) && (
                    <span className="text-emerald-600" title="Edited and accepted">
                      ●
                    </span>
                  )}
                </span>
                <span className="block truncate text-sm text-slate-500">
                  {section.text || "(no body text)"}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit
```

Expected: an additional error at `page.tsx`'s `<SectionList ... />` call site
— missing `editedIds`. Fixed in Task 10.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/components/SectionList.tsx
git commit -m "$(cat <<'EOF'
SectionList: mark sections with an accepted edit

A small dot next to the heading, and a running count in the section summary —
enough to see progress across a multi-section session without a dedicated
progress view.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `ExportPanel.tsx` + wiring `page.tsx`

**Files:**
- Create: `frontend/app/components/ExportPanel.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `exportDocument` (Task 7), `ResultPanel`'s new props (Task 8),
  `SectionList`'s new prop (Task 9).
- Closes out every `tsc` error the last two tasks deliberately introduced.

- [ ] **Step 1: Create `ExportPanel.tsx`**

```tsx
"use client";

import { useState } from "react";
import { exportDocument } from "@/lib/api";

/**
 * The document-level "I'm done" action — deliberately its own component with
 * its own busy/error state, so a failed download is never confused with a
 * failed rewrite in the UI.
 *
 * Uses the global `document` object to trigger the browser download. Kept out
 * of page.tsx on purpose: page.tsx already has a `document` state variable
 * (the uploaded document), which would shadow the browser global there.
 */
export function ExportPanel({
  documentId,
  filename,
  currentTexts,
}: {
  documentId: string;
  filename: string;
  currentTexts: Record<string, string>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setBusy(true);
    setError(null);
    try {
      const blob = await exportDocument({ documentId, sections: currentTexts });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filename.replace(/\.docx$/i, "")}-edited.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-6">
      <h2 className="mb-1 font-semibold">3. Finish up</h2>
      <p className="mb-4 text-sm text-slate-500">
        Downloads every section as it currently stands — accepted edits where
        you made them, the original text everywhere else.
      </p>
      <button
        type="button"
        onClick={handleDownload}
        disabled={busy}
        className="w-full rounded-md bg-slate-800 px-4 py-2 text-sm font-medium
                   text-white hover:bg-slate-700 disabled:opacity-40"
      >
        {busy ? "Preparing…" : "Mark complete & download"}
      </button>
      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Wire `page.tsx`**

Add the import:

```tsx
import { ExportPanel } from "./components/ExportPanel";
```

Add state, right after the existing `selectedId` state:

```tsx
  const [currentTexts, setCurrentTexts] = useState<Record<string, string>>({});
```

Seed it on upload — replace the `onUploaded` callback body:

```tsx
          <UploadPanel
            onUploaded={(uploaded, name) => {
              setDocument(uploaded);
              setFilename(name);
              setSelectedId(null);
              setResult(null);
              setError(null);
              setCurrentTexts(
                Object.fromEntries(uploaded.sections.map((s) => [s.id, s.text])),
              );
            }}
          />
```

Send it with every rewrite — replace `handleInstruction`:

```tsx
  async function handleInstruction(instruction: string) {
    if (!document || !selectedId) return;
    setResult(null);
    await run(() =>
      rewriteSection({
        documentId: document.document_id,
        sectionId: selectedId,
        instruction,
        currentTexts,
      }),
    );
  }

  function handleAccept() {
    if (result?.status !== "complete") return;
    setCurrentTexts((prev) => ({ ...prev, [result.section_id]: result.new_text }));
  }
```

Compute `editedIds` right before the `return`:

```tsx
  const editedIds = new Set(
    (document?.sections ?? [])
      .filter((s) => currentTexts[s.id] !== s.text)
      .map((s) => s.id),
  );
```

Pass the new props to `SectionList`:

```tsx
              <SectionList
                sections={document.sections}
                headingsDetected={document.headings_detected}
                selectedId={selectedId}
                editedIds={editedIds}
                onSelect={(id) => {
                  setSelectedId(id);
                  setResult(null);
                  setError(null);
                }}
              />
```

Mount `ExportPanel` in the left column, right after `SectionList` closes
(still inside the `{document && (...)}` block):

```tsx
              <ExportPanel
                documentId={document.document_id}
                filename={filename ?? "document.docx"}
                currentTexts={currentTexts}
              />
```

Pass the new props to `ResultPanel`:

```tsx
          {result?.status === "complete" && (
            <ResultPanel
              result={result}
              onAccept={handleAccept}
              accepted={currentTexts[result.section_id] === result.new_text}
            />
          )}
```

- [ ] **Step 3: Typecheck — must now be clean**

```bash
npx tsc --noEmit
```

Expected: no output. Every error introduced in Tasks 8–9 is resolved here.

- [ ] **Step 4: Build**

```bash
npx next build
```

Expected: succeeds.

- [ ] **Step 5: Check it by hand in the browser**

Two terminals:

```bash
cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload
cd frontend && npm run dev
```

At `http://localhost:3000`: upload `backend/sample/meridian-proposal.docx`.

1. Rewrite **2. Scope of Work**, click **Accept into final document** — confirm
   the button becomes "Accepted" and a dot appears next to the section in the
   list.
2. Select **4. Fees and Payment**, ask for a change, confirm the conflict
   question (if one comes back) reads correctly.
3. Click **Mark complete & download** — confirm a `.docx` downloads, and open
   it: the scope section should show your accepted edit; every other section
   should read exactly as in the original upload.
4. Confirm downloading **without accepting anything** still produces the
   unmodified original document — not an error.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/components/ExportPanel.tsx frontend/app/page.tsx
git commit -m "$(cat <<'EOF'
Wire up accept-and-download end to end

currentTexts is seeded from the upload, updated only by an explicit Accept
click, sent with every rewrite so later sections see earlier accepted edits,
and handed to ExportPanel for the final download.

ExportPanel is its own component rather than inline in page.tsx specifically
because page.tsx already has a `document` state variable that would shadow the
browser's global document.createElement — the download trigger needs the real
one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

**Spec coverage.** §2–3 (the override reaching later rewrites) → Tasks 1–2.
§4.3 (frozen context across a suspended question) → Task 3, with a test that
constructs a session by hand specifically to prove `resume()` cannot see a
document state different from what it was given. §4.4–4.5 (export module and
endpoint) → Tasks 4–5. §5 (frontend state, accept model, download mechanics) →
Tasks 7–10. §6 (notes never applied, nothing persists) → nothing in this plan
touches notes or adds persistence, so this holds by omission, not by a
specific task. §7 (edge cases) → covered by name in Task 5's tests (missing
id, unknown id, unknown document) and Task 10's manual check (zero edits
accepted still downloads).

**Type consistency.** `overlay_texts` (Task 1) is used unchanged by
`orchestrator.start` (Task 2) and the export endpoint (Task 5) — one function,
two callers, exactly as the spec's §4.1 argued for. `RewriteSession.context`
(Task 2) is read only by `resume()` (Task 3); nothing else touches it.
`current_texts` as a wire field is `dict[str, str]` on the backend and
`Record<string, string>` on the frontend throughout — no task introduces a
different shape for the same concept.

**The one thing worth double-checking in review:** Task 8 and Task 9 each
leave `page.tsx` red under `tsc` on purpose, and Task 10 is what makes it
green again. This mirrors how the ripples-to-notes work earlier in this
project's history was sequenced, and it's deliberate here for the same
reason — the compile error is the evidence that the new props are genuinely
required, not optional additions nobody has to wire up.

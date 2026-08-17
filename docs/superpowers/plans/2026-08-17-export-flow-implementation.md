# Mark Complete & Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user edit more than one section, keep the edits they like,
and download a real Word file with those changes in it. Also: once they've
accepted an edit to one section, a later edit to a *different* section should
know about it — not check against the old, original text.

**How it works:** The browser keeps a running list — "here's the text I've
accepted for each section so far." It sends that list along every time it asks
for a new rewrite. The backend uses that list instead of the original upload
when it checks for conflicts. If the app has to stop and ask the user a
question, it takes a snapshot of the document at that exact moment, so the
answer is never checked against a document that changed underneath it. A small
new file turns sections back into a real Word document, and one new web
address lets the browser download it.

**Tech Stack:** Same as before — Python, FastAPI, Pydantic, pytest,
`python-docx` (already used elsewhere in this project), Next.js, TypeScript,
Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-17-export-flow-design.md` — this plan
builds exactly what that document describes.

## Ground rules for this whole plan

- **No new tools or libraries.** `python-docx` is already used for reading
  Word files; we'll use it for writing them too.
- **Every new feature is "off" unless you use it.** If a request doesn't
  include the new "accepted edits" list, everything behaves exactly like it
  does today. Nothing that already works should change.
- **Tests still run without calling the real AI model.** Same as the rest of
  this project — we fake the model's answers in tests so they run in seconds.
- **No new automated tests on the frontend.** We check the frontend by
  running the TypeScript checker and clicking through it by hand — that's
  already how this project has been doing it.
- **Commit after every task**, and end every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

## Files this plan touches

**New files:**

| File | What it's for |
|---|---|
| `backend/app/export.py` | Turns a list of sections back into a real `.docx` file. |
| `backend/tests/test_export.py` | Tests that check nothing gets lost when we build that file. |
| `frontend/app/components/ExportPanel.tsx` | The "Mark complete & download" button and its own loading/error state. |

**Files we're changing:**

| File | What changes |
|---|---|
| `backend/app/rewrite.py` | Add one small helper function both the rewrite and the download use. |
| `backend/app/store.py` | Save a snapshot of the document alongside any question we ask the user. |
| `backend/app/orchestrator.py` | Accept the "accepted edits so far" list; use the snapshot when answering a question. |
| `backend/app/main.py` | Accept the new list in the rewrite request; add the new download endpoint. |
| `backend/tests/test_rewrite.py`, `test_orchestrator.py`, `test_api.py` | New tests, one per change above. |
| `frontend/lib/api.ts` | Send the accepted-edits list; add a function to download the file. |
| `frontend/app/components/ResultPanel.tsx` | Add an "Accept into final document" button. |
| `frontend/app/components/SectionList.tsx` | Show a small mark next to any section that's been edited. |
| `frontend/app/page.tsx` | Keep track of accepted edits; wire everything together. |

---

## Task 1: A function that fills in the edits you've already accepted

**What this does:** Say you've already accepted a rewrite for section 2. This
function takes the original list of sections and swaps in your accepted text
for section 2, leaving everything else the same. Both the rewrite feature and
the download feature will use this same function, so they never disagree
about what "the current document" looks like.

**Files:**
- Change: `backend/app/rewrite.py`
- Change: `backend/tests/test_rewrite.py`

**What it produces:** a function called
`overlay_texts(sections, current_texts)`. Later tasks call it from two
places: when starting a new rewrite, and when building the file to download.

- [ ] **Step 1: Write the tests first (they should fail right now)**

Add this to `backend/tests/test_rewrite.py` (it reuses the `SECTIONS` list
already at the top of that file):

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
    """If the browser sends an old section id — say, from before a new file
    was uploaded — this should just be ignored, not cause an error."""
    assert overlay_texts(SECTIONS, {"s99": "orphaned"}) == SECTIONS
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

You should see: `ImportError: cannot import name 'overlay_texts'` — that's
expected, since we haven't written it yet.

- [ ] **Step 3: Write the function**

Add this to the end of `backend/app/rewrite.py`:

```python
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
```

- [ ] **Step 4: Run the tests again — they should pass now**

```bash
./.venv/bin/python -m pytest tests/test_rewrite.py -q
```

- [ ] **Step 5: Save this work**

```bash
git add backend/app/rewrite.py backend/tests/test_rewrite.py
git commit -m "$(cat <<'EOF'
Add overlay_texts() — fill in the edits the author already accepted

One function that both the rewrite feature and the download feature will use:
take the original sections, and swap in whatever text the author has already
accepted, section by section. Everything else about the section — its id,
heading, position — stays the same.

If an id doesn't match any real section (for example, a leftover from before
a new file was uploaded), it's just ignored instead of causing an error.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Make new rewrites see edits you've already accepted

**What this does:** Right now, when you rewrite a section, the app only ever
looks at the document as it was first uploaded. This task changes that: it
looks at the document as it currently stands — including any edits you've
already accepted for other sections.

**Files:**
- Change: `backend/app/store.py`
- Change: `backend/app/orchestrator.py`
- Change: `backend/tests/test_orchestrator.py`

**What it needs:** `overlay_texts` from Task 1.

**What it produces:**
- A new field on the saved "waiting for an answer" record: `context`, a
  snapshot of the document at the moment a question was asked.
- The main "start a rewrite" function now optionally takes a
  `current_texts` list of accepted edits.

- [ ] **Step 1: Write the tests first**

Add these to `backend/tests/test_orchestrator.py`, right after the test
called `test_an_unknown_section_is_not_a_crash` (before the line that starts
`from app.question import Branch`):

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


def test_current_texts_reach_the_conflict_check_prompt(document_id, model, monkeypatch):
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


def test_leaving_out_current_texts_still_works_as_before(document_id, model):
    outcome = orchestrator.start(document_id, section_id="s2", instruction="Be concrete.")

    assert isinstance(outcome, orchestrator.Completed)


def test_a_pending_question_saves_a_snapshot_of_the_edited_document(document_id, model):
    model["conflicts"] = [
        Conflict(section_id="s4", quote="A fixed fee of EUR 90,000.",
                 explanation="test", blocking=True)
    ]

    outcome = orchestrator.start(
        document_id, section_id="s2", instruction="Be concrete.",
        current_texts={"s4": "A fixed fee of EUR 90,000."},
    )

    assert isinstance(outcome, orchestrator.Asking)
    saved = {s.id: s.text for s in store.get_session(outcome.session_id).context}
    assert saved["s4"] == "A fixed fee of EUR 90,000."
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Expected error: `TypeError: start() got an unexpected keyword argument 'current_texts'`.

- [ ] **Step 3: Add the snapshot field to the saved session**

In `backend/app/store.py`, add `Section` to the import line:

```python
from .conflicts import Conflict, Note
from .parsing import ParsedDocument, Section
```

Then update the `RewriteSession` class to look like this:

```python
class RewriteSession(BaseModel):
    """A rewrite that's paused, waiting for the user to answer one question.

    `context` is a snapshot: the document exactly as it looked — including any
    edits the author had already accepted — at the moment the question was
    asked. When the answer comes back, we check it against this snapshot, not
    against whatever the document looks like by then. That way the question
    and the answer are always talking about the exact same document.

    `draft_text` is the rewrite we already produced, so answering the question
    doesn't mean starting over from nothing. `asking` is what the question is
    about. `notes` are things we noticed but decided not to ask about — kept
    here so we can still show them in the final result.

    `resolved` marks a session as finished, so answering it twice (say, from
    an old browser tab) gives a clear error instead of quietly running again.
    There's no "how many times have we asked" counter here, because the app
    only ever asks once.
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

- [ ] **Step 4: Make `start()` accept and use the accepted-edits list**

In `backend/app/orchestrator.py`, add `overlay_texts` to the import from
`.rewrite`:

```python
from .rewrite import draft_section, find_section, overlay_texts
```

Then replace the whole `start()` function with this:

```python
def start(
    document_id: str, *, section_id: str, instruction: str,
    current_texts: dict[str, str] | None = None,
) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    # Build the document as it currently stands: accepted edits filled in,
    # original text everywhere else.
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

Everywhere the old code said `document.sections`, it now says `sections`
(the version with your accepted edits filled in). The `old_text` shown to the
user is also now based on this current version — which makes sense, since
"before this edit" should mean "before this edit," not "before anything was
ever edited."

- [ ] **Step 5: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

All should pass. (Any test that answers a question, via `resume()`, may still
fail right now — that's fixed in the next task.)

- [ ] **Step 6: Save this work**

```bash
git add backend/app/store.py backend/app/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Rewrites can now see edits already accepted for other sections

Before this, if you accepted a change to the scope section and then edited
the fees section, the fees check would still compare against the *original*
scope — missing exactly the kind of conflict this app is supposed to catch.

Now the browser can send along the edits it's already accepted, and the app
checks against the document as it currently stands.

When the app has to pause and ask the user a question, it now saves a
snapshot of the document at that exact moment (RewriteSession.context), so the
answer is always checked against the same document the question was about.

None of this changes anything for a request that doesn't include the new
list — everything keeps working exactly as before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Make answering a question use that same snapshot

**What this does:** Task 2 saved a snapshot of the document when a question
was asked. This task makes the "answer the question" function actually use
that snapshot, instead of looking up the document fresh.

**Files:**
- Change: `backend/app/orchestrator.py`
- Change: `backend/tests/test_orchestrator.py`

**What it needs:** the `context` snapshot from Task 2.

- [ ] **Step 1: Write the test first**

Add this to `backend/tests/test_orchestrator.py`, near the other tests about
answering a question:

```python
def test_answering_a_question_uses_the_saved_snapshot_not_the_live_document(
    document_id, model, monkeypatch
):
    """We build a "paused" session by hand here, with a snapshot that
    deliberately says something different from the real document. If
    answering the question uses the snapshot (correct), the fake number shows
    up. If it re-reads the real document instead (wrong), the real number
    shows up."""
    frozen_snapshot = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation within the quarter."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s4", heading="4. Fees and Payment",
                text="A fixed fee of EUR 999,000, frozen at ask time."),
    ]
    session_id = store.save_session(
        store.RewriteSession(
            document_id=document_id, section_id="s2", instruction="Be concrete.",
            draft_text="drafted", context=frozen_snapshot,
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

- [ ] **Step 2: Run it — confirm it fails**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py::test_answering_a_question_uses_the_saved_snapshot_not_the_live_document -q
```

Right now `resume()` still re-reads the live document, so the real fee text
(`"A fixed fee of EUR 48,000 covers it."`) shows up where the snapshot's fake
one should be. That's the failure we expect.

- [ ] **Step 3: Update `resume()` to use the snapshot**

Replace the body of `resume()` in `backend/app/orchestrator.py` with this:

```python
def resume(session_id: str, *, option_key: str) -> Completed | Declined:
    """Answer a paused question.

    Only one of the three answers ("hold the other section") needs a new
    rewrite. The other two mean "go ahead with what I was already shown" — so
    going back to the model there would risk handing back different text than
    what the author actually agreed to.

    This function can only return a finished result or a "declined" — never a
    second question. That's not a rule we remember to follow; it's built into
    what this function is allowed to return.
    """
    session = store.get_session(session_id)
    if session is None:
        raise UnknownSession(session_id)
    if session.resolved:
        raise SessionFinished(session_id)

    # We still check the document itself hasn't disappeared (say, from a
    # server restart) — that check doesn't change. What changes is that we no
    # longer use this document's sections for anything else below; we use the
    # frozen snapshot instead.
    document = store.get_document(session.document_id)
    if document is None:
        raise UnknownDocument(session.document_id)

    branch = Branch(option_key)  # raises a clear error on anything else
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

- [ ] **Step 4: Run the tests**

```bash
./.venv/bin/python -m pytest tests/test_orchestrator.py -q
```

Everything should pass — including all the older tests about answering
questions. They already go through `start()` first, which now always saves a
snapshot, so they exercise the fix automatically without needing changes.

- [ ] **Step 5: Run the whole backend test suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

Everything except `test_api.py` should be untouched by this task, and it
should already be fine too. If something unrelated breaks, stop and figure
out why before moving on.

- [ ] **Step 6: Save this work**

```bash
git add backend/app/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
Answering a question now uses the frozen snapshot

Every place resume() used to look at the live document, it now looks at the
snapshot saved when the question was first asked. The one exception: we still
check that the document itself hasn't disappeared — that's a different check
and it stays.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Turn sections back into a real Word file

**What this does:** Right now the app can only read a `.docx` file and split
it into sections. This task adds the reverse: given a list of sections,
build a real `.docx` file from them.

**Files:**
- New file: `backend/app/export.py`
- New file: `backend/tests/test_export.py`

**What it produces:** a function called `build_docx(sections)` that returns
the raw bytes of a Word file. Task 5 is the only place that calls it.

- [ ] **Step 1: Write the tests first**

Create `backend/tests/test_export.py`:

```python
"""Tests for turning sections back into a .docx file.

Instead of checking the internal details of how python-docx builds a file, we
build a file and then read it right back in with our own reader
(parse_docx). If what comes out matches what went in, we know it worked.
"""

from app.export import build_docx
from app.parsing import Section, parse_docx


def test_a_single_section_comes_back_the_same():
    sections = [Section(id="s1", heading="1. Scope", text="The engagement is advisory.")]

    reread = parse_docx(build_docx(sections))

    assert [s.heading for s in reread.sections] == ["1. Scope"]
    assert reread.sections[0].text == "The engagement is advisory."


def test_several_sections_stay_in_the_same_order():
    sections = [
        Section(id="s1", heading="1. Executive Summary", text="A recommendation."),
        Section(id="s2", heading="2. Scope of Work", text="The engagement is advisory."),
        Section(id="s3", heading="3. Fees", text="A fixed fee of EUR 48,000."),
    ]

    reread = parse_docx(build_docx(sections))

    assert [s.heading for s in reread.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]
    assert [s.text for s in reread.sections] == [s.text for s in sections]


def test_a_section_with_more_than_one_paragraph_comes_back_the_same():
    sections = [Section(id="s1", heading="1. Scope", text="First paragraph.\n\nSecond paragraph.")]

    reread = parse_docx(build_docx(sections))

    assert reread.sections[0].text == "First paragraph.\n\nSecond paragraph."


def test_the_opening_text_before_any_heading_comes_back_correctly():
    sections = [
        Section(id="preamble", heading="(untitled opening)", text="Proposal: Example."),
        Section(id="s1", heading="1. Scope", text="The engagement is advisory."),
    ]

    reread = parse_docx(build_docx(sections))

    assert reread.sections[0].id == "preamble"
    assert "Proposal: Example." in reread.sections[0].text
    assert reread.sections[1].heading == "1. Scope"
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
./.venv/bin/python -m pytest tests/test_export.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.export'` — the file
doesn't exist yet.

- [ ] **Step 3: Write `export.py`**

```python
"""Turn a list of sections back into a real .docx file.

This is the reverse of what parsing.py does. It builds the file the same way
the sample documents in this project are already built: plain text for
anything before the first heading, and a proper "Heading 1" style plus normal
paragraphs for everything else.
"""

from io import BytesIO

from docx import Document

from .parsing import PREAMBLE_HEADING, Section


def build_docx(sections: list[Section]) -> bytes:
    document = Document()

    for section in sections:
        # The opening text (before any real heading) gets no heading style,
        # so when we read it back in, it's correctly recognized as the
        # opening text again — not as its own numbered section.
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

All should pass.

- [ ] **Step 5: Save this work**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "$(cat <<'EOF'
Add export.py — turn sections back into a real .docx file

The reverse of parsing.py. Built the same way the sample documents in this
project already are: plain paragraphs for the opening text, a real heading
style plus body paragraphs for everything else.

Tested by building a file and reading it straight back in, rather than
checking internal details of how python-docx works.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add the download web address

**What this does:** Adds a new web address the browser can send a request to,
to get back a real `.docx` file with the current, accepted edits in it.

**Files:**
- Change: `backend/app/main.py`
- Change: `backend/tests/test_api.py`

**What it needs:** `build_docx` from Task 4, `overlay_texts` from Task 1.

**What it produces:** `POST /documents/{document_id}/export` — send it a list
of `{id, text}` pairs, get back the raw bytes of a `.docx` file.

- [ ] **Step 1: Write the tests first**

Add this to `backend/tests/test_api.py`:

```python
# --- downloading the finished document -------------------------------------


def export(document_id: str, sections: list[dict]):
    return client.post(f"/documents/{document_id}/export", json={"sections": sections})


def test_export_includes_the_text_you_sent(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    reread = parse_docx(response.content)
    scope = next(s for s in reread.sections if s.heading == "2. Scope of Work")
    assert scope.text == "A new, concrete scope."


def test_export_keeps_the_original_text_for_a_section_you_did_not_send(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    reread = parse_docx(response.content)
    fees = next(s for s in reread.sections if s.heading == "3. Fees")
    assert fees.text == PROPOSAL[5][1]


def test_export_ignores_a_section_id_that_does_not_exist(document_id):
    response = export(document_id, [{"id": "s99", "text": "orphaned"}])

    assert response.status_code == 200


def test_export_keeps_the_original_section_order(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [])

    reread = parse_docx(response.content)
    assert [s.heading for s in reread.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]


def test_export_returns_a_clear_error_for_an_unknown_document():
    response = export("nope", [])

    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
./.venv/bin/python -m pytest tests/test_api.py -k export -q
```

Most of these will fail with a `404`, but for the wrong reason: the web
address doesn't exist yet at all, so FastAPI's own generic "not found" kicks
in. You can tell the difference in
`test_export_returns_a_clear_error_for_an_unknown_document` — it checks for
the word "document" in the error message, and FastAPI's generic message just
says `"Not Found"`, which doesn't contain that word. So that one test fails
even though the status code happens to match — which is exactly the sign
we're looking for that the real feature isn't built yet.

- [ ] **Step 3: Add the new web address**

In `backend/app/main.py`, add `Response` to the existing import from
`fastapi`:

```python
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
```

Add two more imports:

```python
from .export import build_docx
from .rewrite import overlay_texts
```

Add this near the bottom of the file, after the existing `answer` function:

```python
class SectionText(BaseModel):
    id: str
    text: str


class ExportRequest(BaseModel):
    sections: list[SectionText]


@app.post("/documents/{document_id}/export")
async def export_document(document_id: str, request: ExportRequest) -> Response:
    """Build the current, edited version of the document into a real .docx
    file, and send it back.

    The order and the headings always come from the document we already have
    saved — never from the request. Only the text comes from the request. If
    the request is missing text for a section, we just use that section's
    original text instead of leaving it blank. If the request includes an id
    we don't recognize, we just ignore it.
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

Everything should pass, including all the older tests.

- [ ] **Step 5: Run the whole backend test suite**

```bash
./.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 6: Save this work**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
Add a web address to download the finished document

We reuse overlay_texts() from Task 1 instead of writing similar logic a
second time — the same function now decides both "what should the AI see
when checking for conflicts" and "what should actually go in the downloaded
file."

The order and headings always come from the document we already have saved,
never from the incoming request — only the text does. That way a broken or
partial request from the browser can't corrupt the document's structure, it
can only be missing some edits (which then just fall back to the original
text).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Let a rewrite request include the accepted-edits list

**What this does:** Right now `orchestrator.start()` can take the
accepted-edits list (from Task 2), but the actual web request from the
browser can't send one yet. This task connects the two.

**Files:**
- Change: `backend/app/main.py`
- Change: `backend/tests/test_api.py`

**What it produces:** the `/rewrite` request can now include
`current_texts`.

- [ ] **Step 1: Write the tests first**

In `backend/tests/test_api.py`, update the existing `rewrite()` helper
function so it can optionally send the new list:

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

Then add these tests:

```python
def test_current_texts_reach_the_rewrite_prompt(document_id, monkeypatch):
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


def test_a_rewrite_request_without_current_texts_still_works(document_id, fake_model):
    response = rewrite(document_id)

    assert response.status_code == 200
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
./.venv/bin/python -m pytest tests/test_api.py -k current_texts -q
```

The first test should fail — but not with the error you might expect. None
of the request formats in `main.py` reject extra fields they don't recognize,
so right now `current_texts` in the request is just silently ignored. The
request goes through, the rewrite happens without the override, and the
renegotiated fee text never shows up where the test looks for it — so the
test fails on that missing text, not on a rejected request. The second test
already passes, since it doesn't depend on the new field at all.

- [ ] **Step 3: Add the field**

In `backend/app/main.py`, update `RewriteRequest`:

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

And pass it through in the `rewrite` function:

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

All should pass.

- [ ] **Step 5: Run the whole backend test suite one more time**

```bash
./.venv/bin/python -m pytest tests/ -q
```

You should see the same number of passing tests as before this whole plan
started, plus everything added in Tasks 1 through 6.

- [ ] **Step 6: Save this work**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
The /rewrite request can now carry the accepted-edits list

Defaults to an empty list, so nothing that already works changes. The backend
side of this whole feature is done: accept an edit, rewrite a different
section, and the second rewrite now knows about the first.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update the browser's connection to the backend

**What this does:** Teaches the frontend's API helper file about the two new
things: sending the accepted-edits list with a rewrite, and downloading the
finished file.

**Files:**
- Change: `frontend/lib/api.ts`

**What it produces:** `rewriteSection()` can now send the accepted-edits
list. A new function, `exportDocument()`, downloads the file. Task 10 is the
only place that calls it.

- [ ] **Step 1: Edit the file**

Replace `rewriteSection` and add `exportDocument` after it:

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
 * Downloads the finished document as a Blob (a file, not text). This
 * endpoint sends back an actual file, so we don't use the usual unwrap()
 * helper, which expects a JSON response.
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

`answerQuestion()` doesn't need to change — as decided in the design, once a
question has been asked, the answer always uses the snapshot the backend
already saved. There's nothing new to send along with the answer.

- [ ] **Step 2: Check the types are still correct**

```bash
cd frontend && npx tsc --noEmit
```

Should show no errors — the new list is optional, and nothing calls
`exportDocument` yet.

- [ ] **Step 3: Save this work**

```bash
git add frontend/lib/api.ts
git commit -m "$(cat <<'EOF'
Frontend can now send accepted edits and download the file

rewriteSection() can carry the accepted-edits list. exportDocument() gets the
finished file back as a downloadable Blob instead of JSON, since this
endpoint sends a real file. answerQuestion() is unchanged — once a question is
asked, the answer always uses the snapshot the backend already saved.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add the "Accept into final document" button

**What this does:** After a rewrite finishes, the user needs a clear way to
say "yes, keep this." This adds that button to the result screen.

**Files:**
- Change: `frontend/app/components/ResultPanel.tsx`

**What it produces:** `ResultPanel` now needs two more pieces of
information passed to it: `onAccept` (what to do when the button is
clicked) and `accepted` (whether this result has already been accepted).
Task 10 supplies both.

- [ ] **Step 1: Edit the component**

The `NoteCard` part of the file doesn't change — only `ResultPanel` itself:

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

- [ ] **Step 2: Check the types**

```bash
npx tsc --noEmit
```

You'll now see an error where `page.tsx` uses `<ResultPanel result={result} />`
— it's missing the two new pieces of information. That's expected. Task 10
fixes it. No other file should show an error.

- [ ] **Step 3: Save this work**

```bash
git add frontend/app/components/ResultPanel.tsx
git commit -m "$(cat <<'EOF'
Add an "Accept into final document" button to the result screen

Nothing is kept automatically — clicking Accept is the only thing that adds a
rewrite to the final document. That way, trying a rewrite you don't like and
running it again never quietly overwrites one you already accepted.

page.tsx doesn't supply the new button's information yet — that's fixed in a
later commit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Show which sections have been edited

**What this does:** Adds a small mark next to any section in the list that
already has an accepted edit, so the user can see their progress at a
glance.

**Files:**
- Change: `frontend/app/components/SectionList.tsx`

**What it produces:** `SectionList` now needs one more piece of
information: `editedIds`, the set of section ids that have an accepted
edit. Task 10 supplies it.

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

- [ ] **Step 2: Check the types**

```bash
npx tsc --noEmit
```

Now there's a second error, at `page.tsx`'s `<SectionList ... />` — it's
missing `editedIds`. Also expected, also fixed in Task 10.

- [ ] **Step 3: Save this work**

```bash
git add frontend/app/components/SectionList.tsx
git commit -m "$(cat <<'EOF'
Show a mark next to sections that have an accepted edit

A small dot next to the heading, plus a running count in the summary line —
enough to see progress across a session with several edits, without needing
a separate progress screen.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Build the download button and connect everything

**What this does:** This is the task that ties everything together. It adds
the "Mark complete & download" button, and wires up the accepted-edits list
across the whole page.

**Files:**
- New file: `frontend/app/components/ExportPanel.tsx`
- Change: `frontend/app/page.tsx`

**What it needs:** `exportDocument` from Task 7, the new button props from
Task 8, the new list prop from Task 9.

**What it fixes:** every error `tsc` has been showing since Tasks 8 and 9.

- [ ] **Step 1: Create `ExportPanel.tsx`**

```tsx
"use client";

import { useState } from "react";
import { exportDocument } from "@/lib/api";

/**
 * The "I'm done, give me the file" button. It has its own loading and error
 * state, kept separate from a rewrite's, so a failed download never looks
 * like a failed rewrite.
 *
 * This file uses the browser's built-in `document` object to trigger the
 * download. It has to live in its own file rather than inside page.tsx,
 * because page.tsx already has a variable named `document` (the uploaded
 * file) — that would hide the real one.
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
        Downloads every section as it currently stands — your accepted edits
        where you made them, the original text everywhere else.
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

- [ ] **Step 2: Wire up `page.tsx`**

Add the import:

```tsx
import { ExportPanel } from "./components/ExportPanel";
```

Add a new piece of state, right after `selectedId`:

```tsx
  const [currentTexts, setCurrentTexts] = useState<Record<string, string>>({});
```

Fill it in when a document is uploaded — replace the `onUploaded` part:

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

Send it along with every rewrite, and add a function for the Accept button —
replace `handleInstruction` with this:

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

Work out which sections have been edited, just above the `return`:

```tsx
  const editedIds = new Set(
    (document?.sections ?? [])
      .filter((s) => currentTexts[s.id] !== s.text)
      .map((s) => s.id),
  );
```

Pass the new information to `SectionList`:

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

Add `ExportPanel` right after `SectionList`, still inside the same
`{document && (...)}` block:

```tsx
              <ExportPanel
                documentId={document.document_id}
                filename={filename ?? "document.docx"}
                currentTexts={currentTexts}
              />
```

Pass the new information to `ResultPanel`:

```tsx
          {result?.status === "complete" && (
            <ResultPanel
              result={result}
              onAccept={handleAccept}
              accepted={currentTexts[result.section_id] === result.new_text}
            />
          )}
```

- [ ] **Step 3: Check the types — should be clean now**

```bash
npx tsc --noEmit
```

No errors expected. Every error from Tasks 8 and 9 should be gone.

- [ ] **Step 4: Build the frontend**

```bash
npx next build
```

Should finish without errors.

- [ ] **Step 5: Try it yourself in the browser**

Open two terminal windows:

```bash
cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload
cd frontend && npm run dev
```

Go to `http://localhost:3000` and upload `backend/sample/meridian-proposal.docx`.

1. Rewrite **2. Scope of Work**, then click **Accept into final document**.
   Check that the button changes to say "Accepted," and a dot appears next
   to the section in the list.
2. Pick **4. Fees and Payment**, ask for a change, and check that the
   question (if there is one) reads correctly.
3. Click **Mark complete & download**. Check that a `.docx` file downloads,
   and open it — the scope section should show your edit, and every other
   section should look exactly like the original.
4. Try downloading **without accepting anything**. It should just download
   the original document, unchanged — not show an error.

- [ ] **Step 6: Save this work**

```bash
git add frontend/app/components/ExportPanel.tsx frontend/app/page.tsx
git commit -m "$(cat <<'EOF'
Connect accept-and-download, start to finish

The accepted-edits list starts out as the original text for every section,
only changes when you click Accept, gets sent along with every rewrite (so
later edits know about earlier ones), and gets handed to ExportPanel for the
final download.

ExportPanel lives in its own file instead of inside page.tsx for a specific
reason: page.tsx already has a variable called `document` (the uploaded
file), which would hide the browser's real `document` object — and the
download button needs the real one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Checking this plan against the design

**Does it cover everything in the design document?** Yes. The part about
later rewrites seeing earlier accepted edits is Tasks 1–2. Freezing the
document when a question is asked is Task 3, with a test built specifically
to prove it — by hand-building a "paused" session whose saved snapshot says
something different from the real document, and checking the snapshot wins.
Turning sections into a file and serving it for download are Tasks 4–5. All
the frontend wiring is Tasks 7–10. Nothing in this plan touches the
"suggestions we show but don't apply" feature or adds any kind of saving
between visits — both stay exactly as they already were, simply by not being
touched.

**Do the pieces fit together correctly?** `overlay_texts` (Task 1) is used
by both `orchestrator.start` (Task 2) and the download address (Task 5) —
one function, two places that need it, exactly as planned. The saved
snapshot (Task 2) is only ever read by the "answer a question" function
(Task 3) — nothing else touches it. The accepted-edits list is a simple
`{id: text}` map on both the backend and the frontend the whole way through
— no task quietly changes its shape.

**One thing worth knowing before you start:** Tasks 8 and 9 deliberately
leave the frontend showing type errors — on purpose. Task 10 is what makes
those errors go away. This is the same pattern used earlier in this
project: the error itself is proof that the new information is genuinely
required, not just something nice to have that nobody actually has to wire
up.

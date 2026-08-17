# Mark Complete & Download — Design

**Date:** 2026-08-17
**Status:** Design approved, not yet implemented. Builds on
[the simplified agent design](2026-08-17-simplified-agent-design.md); nothing in
that spec changes, this one adds a new capability on top of it.

---

## 1. The problem

Today the app rewrites exactly one section and stops. A consultant working
through a real document touches several sections in one sitting — scope,
timeline, fees — and at the end wants one clean `.docx` with everything they
accepted, not five separate before/after panels they have to reassemble by
hand. The original brief listed "export back to `.docx`" as something safe to
cut; this spec reopens it deliberately, at the user's request.

## 2. The decision underneath the feature

Accumulating edits across sections raises a question the UI decision alone
doesn't answer: **if section 2 is edited and accepted, and the author then edits
section 4, does the conflict check on section 4 see the accepted edit to
section 2, or the original text from upload?**

This is not cosmetic. The app's entire premise is "informed by the rest of the
document." Checking section 4 against a section 2 that's already been
superseded is the same silent-inconsistency failure the brief describes, one
level up. This spec treats it as core, not an edge case.

**Decision:** the frontend owns the accumulated state; the backend takes it as
a per-request override and stays exactly as stateless as it is today. No new
mutable document concept in `store.py`. Considered and rejected: a backend
"working copy" mutated by an explicit accept endpoint — it solves the same
problem but adds a second notion of "the document" server-side, and a way for
that copy to drift from the original that has to be reasoned about across a
suspended `needs_clarification` round trip. The override approach doesn't have
that seam.

## 3. Data flow

```
                    ┌─────────────────────────────────────────┐
                    │  Frontend: currentTexts: {section_id: text} │
                    │  seeded from upload, updated only on Accept │
                    └───────────────────┬───────────────────────┘
                                        │ sent with every /rewrite call
                                        ▼
POST /rewrite  { document_id, section_id, instruction, current_texts? }
                                        │
                    orchestrator.start() overlays current_texts onto
                    the stored document's sections before DRAFT/DETECT
                    ever see them — so DETECT reasons about the document
                    as the author currently has it, not as it was uploaded
                                        │
                    ┌───────────────────┴───────────────────────┐
                    ▼                                           ▼
              complete + notes                          needs_clarification
                    │                                           │
        [Accept into final document]              answered against the SAME
        → currentTexts[section_id]                 frozen snapshot the question
          = new_text                                was asked against, via
                                                      RewriteSession.context

                    ┌─────────────────────────────────────────┐
                    │  "Mark complete & download" — always available │
                    └───────────────────┬───────────────────────┘
                                        ▼
POST /documents/{id}/export  { sections: [{id, text}] }
                                        │
                    backend orders by its OWN stored document,
                    falls back to original text for anything missing,
                    ignores anything unknown, builds a .docx
                                        ▼
                          .docx bytes → browser download
```

## 4. Backend changes

### 4.1 The override, precisely

A new helper, next to `render_document` in `rewrite.py` since it operates on
the same `list[Section]` shape everything else already passes around:

```python
def overlay_texts(sections: list[Section], current_texts: dict[str, str]) -> list[Section]:
    """Replace each section's text with the author's current accepted version,
    where one exists. Ids, headings and order are untouched — only what the
    rest of the pipeline reads as "the document" changes."""
    return [
        s.model_copy(update={"text": current_texts[s.id]}) if s.id in current_texts else s
        for s in sections
    ]
```

### 4.2 `orchestrator.start()`

Gains one optional parameter, defaulting to today's exact behaviour when
omitted:

```python
def start(
    document_id: str, *, section_id: str, instruction: str,
    current_texts: dict[str, str] | None = None,
) -> Outcome:
    document = store.get_document(document_id)
    if document is None:
        raise UnknownDocument(document_id)

    sections = overlay_texts(document.sections, current_texts or {})
    ...  # everything below reads `sections`, never `document.sections`, from here on
```

`section.text` in the `Completed` result (the "Before" panel) is therefore the
author's *current* accepted text, not necessarily the pristine upload — correct,
since "before" should mean "before this rewrite," not "before anything ever
happened to the document."

### 4.3 The frozen context across a suspended question

`RewriteSession` gains one field:

```python
class RewriteSession(BaseModel):
    ...
    context: list[Section]   # the overlaid sections view at the moment the
                              # question was asked — resume() reasons against
                              # this, never against a freshly re-overlaid one
```

`start()` sets `context=sections` (the overlaid list, not `document.sections`)
when it saves a suspended `RewriteSession`.

`resume()` keeps its existing `store.get_document(session.document_id)` call
unchanged — that's still how it confirms the document wasn't lost to a
restart, and it's the `UnknownDocument` check. What changes is which sections
get handed to `draft_section`/`find_conflicts`: everywhere `resume()` currently
passes `document.sections` for DRAFT/DETECT content, it passes `session.context`
instead. A HOLD redraft is therefore checked against exactly the document the
author was looking at when they were asked — not a document that could have
silently shifted if `current_texts` on the answer request differed. For that
reason, **`POST /rewrite/{id}/answer` does not accept `current_texts` at
all** — there is nothing to override once a run has suspended; the context is
already fixed.

### 4.4 `app/export.py` — new file

```python
def build_docx(sections: list[Section]) -> bytes:
    """The inverse of parsing.py: sections back into a .docx. Same shape the
    sample-document scripts already use — a plain paragraph for a preamble
    (no heading style), Heading 1 + body paragraphs for everything else, in
    the order given."""
```

Round-trips through the existing `parse_docx()` for its own tests: build,
re-parse, confirm headings and text survive.

### 4.5 `POST /documents/{document_id}/export` — new endpoint, in `main.py`

```
Request:  { sections: [{ id: str, text: str }] }
Response: .docx bytes
          Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
          Content-Disposition: attachment; filename="rewritten-document.docx"
```

Not routed through `orchestrator.py` — there is no decision being made, only
assembly, so it doesn't belong in "the suspendable run." Order and headings
always come from the backend's own stored document, never from the request:
for each stored section, use the request's text if that id is present,
otherwise fall back to the stored original. An id in the request that matches
nothing in the stored document is silently ignored. `404` if the document
itself is unknown.

The filename in `Content-Disposition` is a plain, generic default — useful for
anyone hitting the endpoint directly (`curl`, `/docs`). The frontend overrides
it with a nicer one it already knows how to build (§5), since the browser's
download attribute wins regardless of what the response header says. Adding
filename-tracking to the backend for this alone isn't worth a new field on
`ParsedDocument` that nothing else would use.

## 5. Frontend changes

- `page.tsx` gains `currentTexts: Record<string, string>`, seeded from
  `document.sections` on upload, reset on every new upload exactly like the
  rest of the session state already is.
- Every `rewriteSection()` call now sends `currentTexts`.
- `ResultPanel` gains an **"Accept into final document"** button on a
  `complete` result. Clicking it is the only thing that writes to
  `currentTexts` — a rewrite you don't like and re-run never silently
  overwrites a version you already accepted, because nothing commits except
  that button.
- `SectionList` marks each section whose `currentTexts` entry differs from its
  original upload text — a small dot or checkmark, enough to see progress
  across a multi-section session at a glance.
- A **"Mark complete & download"** control, always available once a document
  is loaded — downloading with zero edits accepted is a valid outcome (the
  unmodified document), not an error state.
- Download mechanics: `fetch` the export endpoint, read the response as a
  `Blob`, build an object URL, trigger it through a temporary `<a download="…">`
  element — the standard pattern, no library. Filename:
  `${originalFilenameStem}-edited.docx`, built from the `filename` state
  `page.tsx` already tracks from upload.

## 6. What doesn't change

- Notes/ripples remain informational only. They are never applied to
  `currentTexts` and never affect the export — the author is still the editor
  of record for anything outside the section they explicitly rewrote and
  accepted.
- Nothing persists across a server restart. `currentTexts` lives in the
  browser tab, same as every other piece of session state today.
- A fresh upload resets everything, `currentTexts` included.

## 7. Edge cases

| Case | Behaviour |
|---|---|
| Download with no edits accepted | Original document, unchanged — valid, not an error |
| Export request missing a section id the document has | Falls back to that section's original text, never dropped |
| Export request includes an id the document doesn't have | Ignored |
| Unknown `document_id` on export | `404` |
| A rewrite of section 4 after section 2 was accepted | DETECT reasons against the accepted section 2, not the upload original — the whole point of §2 |
| A suspended question, then a later `current_texts` change elsewhere | Irrelevant to the suspended run — `resume()` uses the frozen `session.context`, never re-reads current state |

## 8. Testing (for the implementation plan to expand)

- `export.py`: `build_docx()` round-trips through `parse_docx()`.
- `main.py`: the export endpoint — 404 on unknown document, fallback on a
  missing id, ignoring an unknown id, correct headers, correct section order.
- `orchestrator.py`: `start(current_texts=...)` — offline, by asserting the
  overridden text reaches the DETECT prompt (same pattern already used by
  `test_draft_section_sends_the_whole_document`); `resume()` uses
  `session.context`, not a fresh overlay.
- No new frontend automated tests — consistent with the existing project
  decision (frontend verified by `tsc` and a manual click-through), stated
  once in the simplified agent spec and not re-litigated here.

# Section-Aware Rewrite Agent — Design Reference

How the app decides whether a rewrite needs to interrupt the user, and how the rest of the
system fits together.

---

## What the interrupt decision optimizes for

The decision stays small enough to hold in your head at once: one grounded quote, one blocking
judgment, one question — grouped into a single row per affected section when more than one
section is at stake, but never split across more than one round trip.

---

## Architecture

Two AI calls per rewrite in the common case. A third only runs if the author holds at least one
section during the redraft:

```
instruction ──► DRAFT (AI) ──► DETECT (AI) ──► DECIDE (Python) ──► complete + notes
 + section id     writes the        finds conflicts,   groups every         or a question,
 + whole doc      new text          judges blocking      blocking section     one row per
                                     vs informational     into one question    blocking section
                                                                    │
                                                     author answers every row ▼
                                     any row is Hold ──► DRAFT again (combined constraints)
                                                     ──► DETECT again ──► done
                                     no row is Hold  ──► done, unchanged
```

Nothing after the author's answer can produce a second question — `resume()`'s return type has
no case for one.

---

## The interrupt policy

`conflicts.py`'s `decide()` is the whole thing:

```python
def decide(conflicts, sections, rewritten_id) -> Decision:
    conflicts = exclude_self_references(conflicts, rewritten_id)
    grounded = ground(conflicts, by_id, rewritten_id)
    blocking = [c for c in grounded if c.blocking]

    if not blocking:
        return Decision(action="complete", notes=dedupe_notes(to_notes(conflicts, grounded, by_id)))

    blocking_section_ids = list(dict.fromkeys(c.section_id for c in blocking))
    groups = [
        ConflictGroup(section_id=sid, heading=by_id[sid].heading,
                      conflicts=[c for c in blocking if c.section_id == sid])
        for sid in blocking_section_ids
    ]
    non_blocking = [c for c in conflicts if c not in blocking]
    return Decision(action="ask", asking=groups,
                     notes=dedupe_notes(to_notes(non_blocking, grounded, by_id)))
```

Two Python-only checks sit in front of it:

- **`ground()`** — a conflict only counts if its quoted clause is real text in that section. An
  ungrounded conflict never blocks; at worst it's shown as an unverified note.
- **`exclude_self_references()`** — a finding against the section actually being rewritten isn't
  a conflict with another section, it's just the rewrite.

A third pass, `dedupe_notes()`, drops a note that's an exact repeat — same section, quote, and
explanation — of one already kept. This matters on the redraft path: after a Hold, DETECT runs
again and can report the same finding a second time.

The model's own `blocking: bool` judgment is trusted directly — Python never re-derives it from a
keyword list, so the policy has nothing document-specific to fail on.

---

## Modules

| File | Responsibility |
|---|---|
| `config.py` | Loads credentials from `.env`; base64-decodes the API key on load. |
| `llm.py` | The one function every AI call goes through. Retries once on an unparseable response; never retries an outright refusal. |
| `text.py` | `normalize()` — whitespace/case-insensitive text comparison, used for grounding quotes. |
| `parsing.py` | Turns an uploaded `.docx` into a list of sections. Text before the first heading gets a fixed id, `"preamble"`, kept out of the `s1`/`s2`/... numbering. |
| `rewrite.py` | DRAFT — writes the new text for one section, and decides whether the instruction applies at all. Also owns `overlay_texts()`, shared with export. |
| `conflicts.py` | DETECT, plus the whole interrupt policy: `ground()`, `exclude_self_references()`, `decide()`. |
| `question.py` | Turns `decide()`'s groups into a question: one row per section, three lettered options each. No AI call. |
| `orchestrator.py` | Runs one rewrite start to finish — `start()` and `resume()`. `resume()`'s return type has no "ask again" case. |
| `store.py` | In-memory dicts for uploaded documents and paused rewrite sessions. |
| `export.py` | Rebuilds a real `.docx` from the current sections — the reverse of `parsing.py`. |
| `main.py` | The HTTP surface: four endpoints, validation and response mapping only. |

---

## API

```
POST /documents
  multipart file
  → { document_id, sections, headings_detected }

POST /rewrite
  { document_id, section_id, instruction, current_texts }
  → { status: "complete", section_id, old_text, new_text, notes }
  | { status: "needs_clarification", session_id, section_id, groups }
  | { status: "declined", section_id, reason }

POST /rewrite/{session_id}/answer
  { choices: { "<section_id>": "a" | "b" | "c", ... } }   -- one entry per group
  → { status: "complete", ... } | { status: "declined", ... }

POST /documents/{document_id}/export
  { sections: [{ id, text }, ...] }
  → a .docx file
```

`needs_clarification` can never come back from `/answer` — enforced by `resume()`'s return type,
not a runtime check. `choices` must cover exactly the sections named in `groups`; anything else
is a `422`.

Each group in a `needs_clarification` response:

```python
class QuestionGroup(BaseModel):
    section_id: str
    heading: str
    conflicts: list[Conflict]     # quote + explanation per finding
    options: list[Option]         # always Hold / Flag / Accept, in that order
```

`Note` is what a non-blocking or deferred finding becomes in the final result:

```python
class Note(BaseModel):
    section_id: str
    heading: str
    quote: str
    explanation: str
    verified: bool     # false when the quote couldn't be grounded — shown, never hidden
    blocking: bool     # true when this was a real conflict, not just an FYI
```

---

## Answering a question

Three ways to answer each row, generated from Python, not the model:

- **Hold (a)** — reshape the rewrite to fit this section. If any row picks Hold, every held row's
  constraint is combined into a single redraft, then re-checked with DETECT once.
- **Flag (b)** — keep the rewrite as drafted; the finding becomes a note.
- **Accept (c)** — keep the rewrite as drafted; the finding is dropped.

If no row picks Hold, `resume()` makes no new AI call at all — it reuses the draft the author
already saw, since generating a new one they never approved could hand back something different
from what they agreed to.

Every answer is checked against a frozen snapshot of the document (`RewriteSession.context`) —
the document exactly as it looked when the question was asked, not whatever it looks like by the
time the answer comes back.

---

## Keeping edits and exporting

Accepted edits are tracked as a `{section_id: text}` map, sent as `current_texts` on later
`/rewrite` calls so a rewrite of one section sees edits already accepted on another. The same map
is sent to `/documents/{id}/export`, which rebuilds a real `.docx`: section order and headings
always come from the stored document, and only the text comes from the request.

---

## Multi-document generalization

Nothing in the code assumes a document's subject matter:

- No keyword list tied to money, dates, or any other domain vocabulary — the model's own
  `blocking` judgment is trusted instead.
- No hardcoded heading text or section count anywhere in a prompt or in application code.
- Section ids are always derived from parsing, never assumed — DETECT's response schema is built
  per request, restricted to this document's real ids.
- Prompts speak generically about "a commitment: a number, a date, a deliverable, an obligation,
  a boundary" — never about a fee specifically.

Three sample `.docx` documents exist for this reason (`backend/sample/`): a consulting proposal,
an internal policy with no money language at all, and a project charter. The opt-in calibration
suite (`RUN_LIVE_TESTS=1 pytest tests/test_calibration.py`) runs the real model against all three.

---

## Edge cases

| Case | Handled in |
|---|---|
| No heading styles found | `parsing.py` — falls back to blank-line splitting, `headings_detected: false` |
| Non-`.docx` upload, empty document | `parsing.py` / `main.py` — `400` |
| Model returns invalid JSON, or an id outside the schema | `llm.py` retries once, then raises `ModelRefusal` → `502`; DETECT's dynamic schema makes an invalid id a validation failure, not something to guess back into shape |
| Instruction makes no sense for the section | `rewrite.py`'s `applicable` flag → `declined`, before a DETECT call is ever spent |
| A hallucinated conflict | `ground()` — reported as an unverified note, never blocking |
| Duplicate or stale answer | `RewriteSession.resolved` → `409` |
| Answer missing or extra sections | `orchestrator.AnswerMismatch` → `422` |
| Unknown document / section / session | `404`, with a readable message |

---

## Testing

- `conflicts.py` — `ground()` and `decide()` against hand-built findings, including dishonest
  ones: a wrong quote, a self-referencing section, two different blocking sections at once.
- `orchestrator.py` — every answer branch, the double-answer guard, decline-before-detect,
  holding more than one section at once.
- `main.py` — the endpoint contract and the edge cases above.
- Opt-in, real-model calibration tests across three different sample documents, so a passing
  suite is evidence the policy generalizes rather than evidence it fits one document's vocabulary.

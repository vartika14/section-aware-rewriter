# Section-Aware Rewrite Agent — Simplified Design (Restart)

**Date:** 2026-08-17
**Status:** Supersedes [the 2026-08-13 spec](2026-08-13-section-rewrite-agent-design.md) and its
phase 4 addendum. This is a technical plan only — no code changes yet. Step 2, after this is
reviewed, is implementation.

---

## 0. Why this document exists

The 2026-08-13 spec and its phases 0–4 are not a wrong turn — they measured something real against
the real model, and several of those findings still hold and are kept below. But the design grew
one addendum at a time across four build phases, and each addendum was locally justified and
globally costly. The result: `loop.py` (293 lines) and `policy.py` (227 lines) together hold seven
distinct concepts a reviewer has to carry at once to understand one decision — *should this
interrupt the user* — and two of those seven (`asked_section_ids`, the `flagged`/`ripples` split)
exist only to patch bugs the first six concepts caused. That is not a 25-minute conversation, and it
is not a design that was ever tested against more than one document's vocabulary.

This restart keeps what was validated and cuts what was complexity managing itself.

**Kept, because it was measured, not assumed:**

- `.docx` only, heading-style parsing — real structure beats inferred structure
- Draft and conflict-detection as **separate model calls** — a model asked to write and critique in
  one breath rationalises. Confirmed by watching it happen.
- Whole-document context, no RAG, no embeddings — the document fits in one context window
- No agent framework — the orchestration is the thing being graded
- Structured outputs through one seam (`llm.py`), one retry on a schema violation, no retry on an
  outright refusal
- A deterministic, Python-side **grounding check** — no finding is trusted with a quote that isn't
  verified in the actual text. This is the one piece of "don't trust the model" worth keeping, and
  it is kept in a form that generalises to any document rather than one tuned to money and dates.
- The exhaustive three-way resolution — *hold the other section*, *apply and flag it*, *apply and
  accept it* — because it is a genuine structural fact (any two conflicting statements have exactly
  these three resolutions), not a heuristic
- The decline path for an instruction that makes no sense on the selected section
- Ripples/notes are informational only, **never applied outside the selected section**

**Cut, because it was either accreted or overfit to one document:**

| Cut | Why |
|---|---|
| The two-round cap, `asked_section_ids`, the `flagged`/`ripples` split, assumption text | All four exist to manage a multi-round conversation. Removing the second round removes the reason for all four at once. |
| Auto-resolve-without-asking (`resolvable_from_document`, `deriving_quote`/`deriving_section_id` double citation, the self-reference guard on resolutions) | Never required by the brief — its own example is ask → answer → done, nothing silent. It bought a feature the brief didn't ask for at the cost of the single riskiest code path in the app. |
| `quotes_a_commitment` — a regex over `fee`, `EUR`, `USD`, `GBP`, `capped at`… | This is the one piece of the old design that is **document-specific**. It works on a consulting proposal about money and fails silently on a policy document about approval thresholds or a spec about a rollout date. Directly in scope for "solve for multiple documents." |
| `_repair_id` and its three fallback strategies for a malformed section id | A workaround for the model returning text outside the schema's contract. The real fix is a schema the model cannot violate — see §4.4. |

---

## 1. The brief, re-read

*(From the assignment PDF, not from repo memory.)*

Upload a 2–4 page document → parse it into sections → the user picks one and describes a change in
plain language → an agent rewrites that section with whole-document context → **if the instruction
now conflicts with something else in the document, the agent stops and asks a specific question
instead of guessing** → the user answers → the agent continues.

*"How you detect conflict, how you decide it's worth interrupting a human for, and how you word the
question: that's what we'll spend most of the session on."* Everything else — upload, parsing, the
rewrite call itself — is scaffolding that must work and earns nothing on its own.

The interaction example in the brief is a **single round trip**: one question, three lettered
options, one answer, done. It does not show a second question. Section 2 below leans on that.

Explicitly permitted: "any libraries, any agent framework, or none at all." Explicitly out of scope:
deployment, auth, persistence across restarts, visual design beyond Tailwind defaults, export,
version history, collaborative editing, exhaustive test coverage. *"A few tests on the parts you
consider risky says more than 80% coverage."*

The test document is **bring-your-own**, and *"choosing a document that makes the conflict problem
visible is part of the exercise."* Nothing in the brief says one document — and grading on "code
quality... easy for the next developer to change" cuts against a design that only works on the
vocabulary of the one document it was built against.

---

## 2. Decisions made here — flag any of these

Six calls that shape everything downstream. Each is reversible; none is hidden.

1. **The agent asks the user a clarifying question at most once per rewrite. Never twice.**
   Not "capped at two" — there is no cap counter anywhere in the new design, because there is no
   loop to cap. `start()` may return a question; `resume()` always returns a final result. This is
   provable by reading the function signatures, not by testing a counter.
2. **No silent auto-resolution.** Every conflict the audit finds is either **blocking** (asks) or a
   **note** (reported, never applied). The category of "the document already answers this, so fix it
   without asking" is gone. It was never required, and it was the single largest source of
   complexity for a feature nobody asked for.
3. **The model's own judgment of `blocking: bool` is trusted directly**, with the three-way taxonomy
   kept only as reasoning scaffolding in the prompt, not as a field Python second-guesses. Python's
   only safety net is: does the quoted text actually exist in the section it's attributed to, and is
   that section not the one being rewritten. This directly uses the room you gave — *"ok with extra
   LLM calls if required for conflict detection"* — by trusting the detection call's judgment instead
   of layering a document-specific keyword list on top of it.
4. **Section ids are enforced by the schema, not repaired after the fact.** The response schema for
   the conflict-detection call is built per-request with the section id field typed as a `Literal`
   over the ids actually in this document. The model cannot return an id that doesn't exist — Pydantic
   validation rejects it before it ever reaches application code, and that failure goes through the
   existing one-retry path in `llm.py`.
5. **Text before the first heading is not a numbered section.** It is folded under a fixed id
   (`"preamble"`) rather than consuming `s1` and shifting every subsequent number by one. This was a
   real, repeatedly-confusing bug in the old design (silently misaimed three calibration tests) and
   it is a parsing decision, not a policy decision — worth fixing at the source.
6. **At least two structurally different sample `.docx` documents get built and used in both fixtures
   and live tests** — not one proposal reused everywhere. Detailed in §7.

---

## 3. Architecture

Two model calls per rewrite in the common case, a third only when the user picks the branch that
needs new text, a fourth (optional, best-effort) to phrase the question:

```
instruction ──► DRAFT (llm) ──► DETECT (llm) ──► DECIDE (python) ──► complete + notes
 + section id                    finds conflicts,      one grounding                or one question
 + whole doc                     judges blocking        check, no more
                                  vs informational
                                                                          │
                                                              user answers ▼
                                                    (a) hold ──► DRAFT again ──► DETECT again ──► done
                                                    (b) flag ──► done, unchanged, finding kept as a note
                                                    (c) ignore ─► done, unchanged, nothing kept
```

Nothing after the user's answer can produce a second question. Branch (a) re-checks the new text —
because it is new and unchecked — but whatever that re-check finds becomes a **note on the finished
result**, never a second interrupt.

---

## 4. Modules

10 files, each with one job. Compare to the current 11 files / 1,465 lines, where `loop.py` and
`policy.py` alone are 520 lines holding seven interacting concepts — the target here is roughly half
that, and more importantly, **two concepts instead of seven** for the part that gets read aloud in
the session.

| File | Responsibility | Rough size |
|---|---|---|
| `config.py` | Credentials — unchanged | ~60 lines |
| `llm.py` | The one seam — unchanged, keeps the temperature-pin and retry-nudge | ~85 lines |
| `text.py` | `normalize()` — unchanged | ~15 lines |
| `parsing.py` | `.docx` → sections. Revised: preamble is `"preamble"`, never `s1` | ~90 lines |
| `rewrite.py` | `draft_section()` — one call, whole-doc context, `{applicable, new_text}` | ~50 lines |
| `conflicts.py` | `find_conflicts()` — one call, dynamic schema (§4.4); `ground()` — the one Python check; `decide()` — ask / complete, ~15 lines | ~90 lines |
| `question.py` | Python builds the three options from the primary conflict group; an optional LLM call polishes the wording, same verify-or-fall-back pattern as before | ~90 lines |
| `orchestrator.py` | `start()`, `resume()` — the whole state machine. No cap, no round counter, no suppression list | ~80 lines |
| `store.py` | In-memory dict; `RewriteSession` — 6 fields, down from 9 | ~50 lines |
| `main.py` | HTTP surface — three endpoints, validation and mapping only | ~150 lines |

### 4.1 `rewrite.py` — DRAFT

Unchanged in spirit from the old `agent.py`. One addition: the applicability check moves **here**,
so an instruction that makes no sense for the section is caught before a conflict-detection call is
even spent on it.

```python
class DraftResult(BaseModel):
    applicable: bool
    inapplicable_reason: str | None = None
    new_text: str | None = None   # None when not applicable
```

### 4.2 `conflicts.py` — DETECT, GROUND, DECIDE

```python
class Conflict(BaseModel):
    section_id: str          # constrained to real ids at request time — see §4.4
    quote: str                # exact text from that section
    explanation: str
    blocking: bool            # the model's own judgment — trusted directly
```

The system prompt keeps the three-way taxonomy from before — contradiction, invalidated premise,
stale reference — as **reasoning guidance only**: it improves the model's judgment about `blocking`
without giving Python a field to argue with. Nothing branches on it.

```python
def ground(conflicts: list[Conflict], sections_by_id: dict[str, Section],
           rewritten_id: str) -> list[Conflict]:
    """Keep only conflicts whose quote is real, and that aren't the section being rewritten."""
    return [
        c for c in conflicts
        if c.section_id != rewritten_id
        and c.section_id in sections_by_id
        and normalize(c.quote) in normalize(sections_by_id[c.section_id].text)
    ]

def decide(conflicts: list[Conflict], grounded: list[Conflict]) -> Decision:
    """Ungrounded conflicts never block — a possibly hallucinated conflict must not
    interrupt anyone, the same asymmetry the old design measured and kept.

    `to_notes` marks a conflict `verified=True` when it's in `grounded`, `False`
    otherwise — an ungrounded finding is shown, never hidden, just never blocking.
    """
    blocking = [c for c in grounded if c.blocking]
    if not blocking:
        return Decision(action="complete", notes=to_notes(conflicts, grounded))

    primary_section = blocking[0].section_id
    primary = [c for c in blocking if c.section_id == primary_section]
    # Everything else this round — a different blocking section, or a non-blocking
    # finding — is not asked about. It becomes a note instead, which is what makes
    # "at most one question, ever" possible without a cap or a suppression list.
    deferred = [c for c in conflicts if c not in primary]
    return Decision(action="ask", asking=primary, notes=to_notes(deferred, grounded))
```

This is the entire interrupt policy. It is shorter than the old `policy.py` by a factor of ten and
still carries the one asymmetry worth keeping: an ungrounded conflict is reported, never a question.

### 4.3 `question.py`

Unchanged pattern from before — Python builds three lettered options from the primary conflict
group, an LLM call may polish the wording, and polished output is discarded if it renumbers the
options or drops every quote. This part of the old design was never the source of complexity and
stays close to as-is.

### 4.4 The schema trick that replaces `_repair_id`

`find_conflicts()` builds its response schema **per request**, once the document's real section ids
are known:

```python
def _conflict_schema(section_ids: list[str]) -> type[BaseModel]:
    SectionId = Literal[*section_ids]   # PEP 646 star-unpacking, Python 3.11+
    return create_model(
        "Conflict",
        section_id=(SectionId, ...),
        quote=(str, ...),
        explanation=(str, ...),
        blocking=(bool, ...),
    )
```

A model that tries to return `"4. Fees and Payment (s5)"` fails schema validation outright — which
already goes through `llm.py`'s one retry — rather than silently producing an unmatched id that has
to be guessed back into shape after the fact. This closes the same bug the old `_repair_id` patched,
at the layer where it actually belongs.

### 4.5 `orchestrator.py`

```python
class RewriteSession(BaseModel):
    document_id: str
    section_id: str
    instruction: str
    draft_text: str
    asking: list[Conflict]     # what the pending question is about
    notes: list[Note]          # already decided, carried to the final result
    resolved: bool = False


def start(document_id, *, section_id, instruction) -> Outcome: ...
    # DRAFT. If not applicable -> Declined.
    # DETECT -> ground -> decide.
    #   complete -> Completed(notes=...)
    #   ask      -> save session, return Asking(...)

def resume(session_id, *, option_key) -> Outcome: ...
    # session.resolved guards a stale/duplicate answer -> SessionFinished
    branch = Branch(option_key)
    if branch is Branch.HOLD:
        draft = draft_section(..., constraint=hold_constraint(session.asking))
        conflicts = find_conflicts(...)
        found = ground(conflicts, ..., rewritten_id=session.section_id)
        # Whatever this finds becomes notes on the result. It is NEVER asked about
        # — re-checking the new text is right, re-interrupting the author is not.
        return Completed(new_text=draft.new_text, notes=session.notes + to_notes(conflicts, found))
    # FLAG or IGNORE: the stored draft, untouched. FLAG keeps the asked conflicts as
    # notes (already grounded when they were first found); IGNORE drops them.
    kept = to_notes(session.asking, session.asking) if branch is Branch.FLAG else []
    return Completed(new_text=session.draft_text, notes=session.notes + kept)
```

No cap, no `asked_section_ids`, no `flagged` list separate from `notes` — there is only ever one
round, so there is nothing to separate. `resume` cannot return `Asking`; its return type says so.

---

## 5. API

Same three endpoints, simplified response shapes:

```
POST /documents                       → { document_id, sections, headings_detected }

POST /rewrite
  { document_id, section_id, instruction }
  → { status: "complete", old_text, new_text, notes: [...] }
  | { status: "needs_clarification", session_id, question, options: [{key, label}] }
  | { status: "declined", reason }

POST /rewrite/{session_id}/answer
  { option_key: "a" | "b" | "c" }
  → { status: "complete", old_text, new_text, notes: [...] }
  | { status: "declined", reason }        # only if a stale/duplicate answer, see below
```

`needs_clarification` **cannot appear from `/answer`** — the type system enforces it, not a runtime
check. A double-answered or unknown session is a `404`/`409` at the HTTP boundary, same handling as
before.

`Note` replaces both `Ripple` and `assumptions`:

```python
class Note(BaseModel):
    section_id: str
    heading: str
    quote: str
    explanation: str
    verified: bool     # false when the quote couldn't be grounded — shown, never hidden
```

---

## 6. Multi-document generalisation

This is the part the old design never actually tested. Concretely:

**Nothing in the code may assume a document's subject matter.** Checklist for the implementation
step:
- No keyword list tied to money, dates, or any other domain vocabulary (§0 — the reason
  `quotes_a_commitment` is cut, not kept-and-widened)
- No hardcoded heading text or section count anywhere in a prompt or in application code
- Section ids are always derived from parsing, never assumed (§4.4's dynamic schema is exactly this
  principle applied to the model's output too)
- Prompts speak generically — *"a commitment: a number, a date, a deliverable, an obligation, a
  boundary"* — never *"a fee"* specifically

**Three sample `.docx` documents, not one**, built for development and testing:

1. A consulting proposal (revised in your own words from the existing Meridian document — money and
   deliverables)
2. An internal policy — e.g. an expense or remote-work policy with an approval threshold in one
   section and a deadline in another, no money language at all
3. A short project charter or feature spec — a rollout date in one section, a scope boundary in
   another

Each is picked specifically to make a *different kind* of commitment collide — a domain-specific
regex would visibly fail on at least one of the three, which is the point.

**Live calibration tests span at least two of the three documents**, not just the first one, so a
passing suite is evidence the design generalises rather than evidence it was tuned to a fixture.

---

## 7. Edge cases

Unchanged from the brief, mapped to where each now lives:

| Case | Handled in |
|---|---|
| No heading styles found | `parsing.py` — blank-line fallback, `headings_detected: false` |
| Non-`.docx` upload, empty document | `parsing.py` / `main.py` — `400` |
| Model returns invalid JSON / an id outside the schema | `llm.py` — one retry, then `ModelRefusal` → `502`; the dynamic schema (§4.4) turns the old id-guessing bug into an ordinary schema-validation retry |
| Instruction makes no sense for the section | `rewrite.py`'s `applicable` flag → `Declined`, checked before a conflict-detection call is spent |
| A hallucinated conflict | `ground()` — reported as an unverified note, never blocking |
| Duplicate or stale answer | `RewriteSession.resolved` → `409` |
| Unknown document / section / session | `404`, readable message |

---

## 8. Testing strategy

Leaner by design — the brief's own guidance is *"a few tests on the parts you consider risky says
more than 80% coverage."* Target roughly 40–60 offline tests (down from 124, because the thing being
tested has fewer branches, not because less is covered):

- `parsing.py` — heading fallback, preamble handling, empty/non-docx rejection
- `conflicts.py` — `ground()` against hand-built conflicts including dishonest ones (wrong quote,
  self-referencing section); `decide()` — ask vs complete, grouping by section
- `orchestrator.py` — the three branches, the double-answer guard, decline-before-detect
- `main.py` — the endpoint contract and the edge-case table above
- **Live calibration, across at least two of the three sample documents** — the true negative, the
  brief's own fee example, and one case per non-proposal document proving the taxonomy holds outside
  a consulting-document vocabulary

---

## 9. Build order

| # | Step | Exit criterion |
|---|---|---|
| 0 | Confirm Azure credentials still resolve | one real call succeeds — already proven, quick recheck only |
| 1 | `parsing.py` + `POST /documents` | a `.docx` dropped in the browser lists its sections, preamble excluded from numbering |
| 2 | `rewrite.py` + naive `/rewrite` (no detection yet) | select a section, get new text, no conflict logic |
| 3 | `conflicts.py` (`find_conflicts`, `ground`, `decide`) | structured `Conflict[]`; `decide()` unit-tested against hand-built findings |
| 4 | `orchestrator.py` + `POST /rewrite/{id}/answer` | the full loop: ask once, answer, done — never a second question |
| 5 | Frontend: upload, section list, instruction, question panel, result with notes | demoable end to end |
| 6 | The second and third sample documents; multi-document calibration tests; README | phase complete |

---

## 10. Explicitly out of scope

Unchanged from the brief: deployment, CI/CD, containers, auth, multi-tenancy, persistence across
restarts, visual design beyond Tailwind defaults, export back to `.docx`, version history,
collaborative editing, exhaustive coverage.

**Newly explicit, as a direct consequence of §2:**
- More than one clarification round, ever
- Silently resolving a conflict without asking, for any reason
- Applying a note/ripple outside the section the user selected — unchanged from before, restated
  because it still matters

---

## 11. Before / after, at a glance

| | Old | New |
|---|---|---|
| Backend files | 11 | 10 |
| Backend LOC | ~1,465 | ~760 (estimate) |
| Concepts behind "should this ask?" | 7 — `kind`, `quotes_a_commitment`, `is_verified`, `is_resolvable`, deriving-quote self-reference, `asked_section_ids`, flagged-vs-ripples | 2 — grounded, blocking |
| Clarification rounds | up to 2, with a cap and a suppression list | exactly 0 or 1, provable from the return types |
| Section-id mismatches | repaired after the fact, 3 fallback strategies | prevented by the schema, 0 fallback strategies |
| Document-specific logic | one regex tied to money/fee vocabulary | none |
| Sample documents | 1 | 3, spanning different domains |
| Offline tests | 124 | ~40–60 (target) |

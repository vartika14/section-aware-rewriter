# Section-Aware Rewrite Agent — Design

**Date:** 2026-08-13
**Context:** Sherpa selection assignment, Senior Software Developer
**Timebox:** 4–8 hours build, two-week deadline
**Deliverables:** git repo, five-minute README, 45-minute session (10 demo / 25 design / 10 Q&A)

---

## 1. The problem

A consultant edits one section of a proposal. The pricing section quoted a fixed fee against the
old wording, the timeline assumed three phases, and the page-one summary promised something else
again. One edit, three silent inconsistencies.

Build a web app where a user uploads a 2–4 page document, picks one section, describes in plain
language how it should change, and an AI agent rewrites it consistently with the whole document —
stopping to ask a specific question when the instruction cannot be satisfied without breaking
something else.

## 2. What is actually being graded

Sherpa's brief is explicit: *"How you detect conflict, how you decide it's worth interrupting a
human for, and how you word the question: that's what we'll spend most of the session on."*

Upload, parsing, section detection and the rewrite itself are scaffolding. They must work. They
earn nothing. Every design decision below is made in service of the clarification loop, and time
is cut from everything else first.

The human-centred criterion sets the calibration target: *"Interrupt them too often and they'll
stop using it — never, and they'll stop trusting it."* Precision matters as much as recall. An
agent that asks about everything fails, it just fails less visibly.

## 3. Conflict taxonomy

Three distinct kinds of consequence follow a section rewrite. Conflating them is the central
mistake, because only one of them justifies interrupting a human.

| Kind | Example | Response |
|---|---|---|
| **Contradiction** | New scope names four workstreams; timeline says three phases | Flag. The fix is mechanical and derivable. |
| **Invalidated premise** | Fixed fee was priced against the *old* wording; the basis has changed | **Ask.** Only the human knows if the fee still holds. |
| **Stale reference** | Page-one summary now describes something slightly different | Propose a ripple edit. Do not ask. |

## 4. The interrupt policy

```
1. Does the rewrite change a commitment?
   (a number, a date, a deliverable, an obligation, a boundary)
   No  → rewrite, stay silent.

2. Does any other section depend on that commitment?
   No  → rewrite, stay silent.

3. Can the correct resolution be derived from the document itself?
   Yes → resolve it, and show the user what changed.
   No  → ask.
```

Step 3 is the hinge. "Derivable" means the document already contains the answer — if pricing caps
stakeholder interviews at twelve, honouring that cap needs no human. "Not derivable" means the
answer lives in the consultant's head or in a client conversation — whether a fixed fee still
covers an added phase is written nowhere.

Findings that share an answer collapse into **one** question. Interrupt fatigue is a failure mode:
a human who is asked four questions stops reading at the second.

## 5. Question wording

A good question names the exact clause it is worried about, quotes it, offers lettered branches
rather than an open prompt, states the downstream consequence of each branch, and is answerable in
one word.

Failure modes to avoid:
- Re-asking the instruction ("Do you want me to make the scope more concrete?")
- Vague warnings with no action ("This may affect pricing. Continue?")
- One question per finding

## 6. Architecture

The agent is a three-step pipeline that can suspend. It is not a framework and not an autonomous
loop.

```
  instruction    ┌──────────────────────────────────────────┐
  + section id → │  1. DRAFT   (LLM)                        │
  + whole doc    │  Rewrite the selected section.           │
                 └──────────────────┬───────────────────────┘
                                    ↓ candidate text
                 ┌──────────────────────────────────────────┐
                 │  2. AUDIT   (LLM, separate call)         │
                 │  old + new + every other section         │
                 │  → Finding[] as structured JSON          │
                 └──────────────────┬───────────────────────┘
                                    ↓
                 ┌──────────────────────────────────────────┐
                 │  3. DECIDE  (pure Python, no LLM)        │
                 │  apply the interrupt policy              │
                 └────────┬───────────────────┬─────────────┘
                          ↓                   ↓
                  complete: text +     suspend: question +
                  flagged ripples      lettered options
                                              ↓ user answers
                                       resume at DRAFT with the
                                       answer as an added constraint
```

### 6.1 Why DRAFT and AUDIT are separate calls

A model asked to write and critique in one call rationalises its own output. The audit call is
also framed neutrally — *"here is a section, here is a proposed replacement, here is the rest of
the document, what breaks?"* — with no indication it is reviewing its own work.

### 6.2 Why DECIDE contains no LLM call

The interrupt policy is the thing being assessed. As deterministic Python it can be read, unit
tested, and defended in the session by pointing at a function. As a prompt it would be a vibe.

### 6.3 Context strategy

A 2–4 page document fits comfortably in one context window. The whole document is sent on every
call. **No embeddings, no retrieval, no vector store.** Knowing when not to reach for RAG is part
of the answer, and the README will say so explicitly.

### 6.4 Audit schema

```python
class Finding(BaseModel):
    section_id: str                    # which other section conflicts
    quote: str                         # exact text from that section
    kind: Literal["contradiction", "invalidated_premise", "stale_reference"]
    explanation: str
    resolvable_from_document: bool     # the hinge of section 4, step 3
    proposed_fix: str | None

class AuditResult(BaseModel):
    instruction_applicable: bool       # false when the instruction makes no
    inapplicable_reason: str | None    #   sense for the selected section
    findings: list[Finding]
```

Requiring `quote` grounds each finding in real text and makes hallucinated conflicts visible.

`instruction_applicable` sits on the result rather than inside `Finding` because it is not a
conflict *with another section* — it has no `section_id` to point at. When it is false, DECIDE
short-circuits and the agent declines rather than mangling the section confidently.

**Ripples**, in the API below, are the `Finding`s that DECIDE did not consider worth interrupting
for — returned alongside the completed rewrite, each with its `quote` and `proposed_fix`, for the
consultant to accept by hand.

## 7. API

Both endpoints return the same discriminated shape, so the frontend renders on `status` alone.

```
POST /documents
  multipart .docx
  → { document_id, sections: [{ id, heading, text }] }

POST /rewrite
  { document_id, section_id, instruction }
  → { status: "complete",  new_text, old_text, ripples: [...] }
  | { status: "needs_clarification", session_id, question, options: [{key, label}] }

POST /rewrite/{session_id}/answer
  { option_key }
  → same two shapes
```

Clarification is capped at **two rounds**. After that the agent proceeds and states its assumption
in the result rather than asking again.

## 8. State

Persistence across restarts is out of scope per the brief. A module-level
`dict[str, RewriteSession]` holds suspended runs. A `RewriteSession` carries the document, the
section id, the original instruction, the findings that triggered the question, and the answers
received so far. Resume re-enters DRAFT with the answer appended as an additional constraint.

## 9. Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | FastAPI | Pydantic native, async, `/docs` is demoable |
| Parsing | `python-docx`, `.docx` only | Real heading styles. PDF is a bag of positioned text and would consume the budget for zero rubric credit |
| Frontend | Next.js + Tailwind, one client component | Matches the suggested stack; no server components, no API routes |
| Transport | Browser → FastAPI directly, CORS enabled | A Next.js proxy layer buys nothing |
| LLM | `openai` SDK, `AzureOpenAI` client, structured outputs | Key supplied by Sherpa |
| Agent framework | **None** | The orchestration is the thing being graded; outsourcing it hides the judgement. Also: "be able to explain every line you hand in" |

## 10. Error handling and messy edges

Named as an assessment criterion, so handled deliberately rather than incidentally:

- **Unparseable headings** — if no heading styles are found, fall back to blank-line block
  splitting and tell the user the sections are a guess.
- **Model returns invalid JSON** — schema validation with one retry, then a clear error to the UI.
  Never a silent partial result.
- **Instruction makes no sense for the section** — `AuditResult.instruction_applicable` is false,
  DECIDE short-circuits, and the agent declines with a reason rather than mangling the section
  confidently.
- **Empty or non-`.docx` upload** — rejected at the endpoint with a readable message.

## 11. Test document

Invented, non-confidential, ~3 pages, with deliberately interlocking sections: an executive summary
making a timing promise, a vague scope, a phased timeline, a fixed fee that cites the scope by
reference and caps a countable quantity, and an exclusions section drawing a line the scope only
gestures at.

The demo must include a **true negative** — an instruction that changes no commitment and produces
a silent rewrite. Demonstrating calibration is worth more than demonstrating detection.

## 12. Build order

| # | Phase | Time | Exit criterion |
|---|---|---|---|
| 0 | Azure smoke test | 0.5h | A script prints a populated Pydantic object from a real Azure call |
| 1 | Upload → parse → sections | 1h | A `.docx` dropped in the browser lists its headings |
| 2 | Naive rewrite | 1h | Select section, type instruction, see new text. No conflict logic |
| 3 | Audit + decide | 2h | Structured `Finding[]` returned; pure-Python policy decides ask/don't-ask |
| 4 | Clarification loop | 1h | Question renders, option clicked, rewrite completes |
| 5 | Edges, fixtures, README | 1h | 3–4 fixture cases including a true negative; README written |

Phase 0 runs first because a dead key or a deployment without structured-output support must be
discovered in minute twenty, not hour five. Phase 2 exists to prove the plumbing while the stakes
are low and is largely superseded by phase 3. The build is demoable from the end of phase 2 onward.

If phases 0–2 overrun, cut phase 5's fixtures. Never cut into phase 3.

## 13. Deliberately out of scope

Per the brief: deployment, CI/CD, containers, authentication, multi-tenancy, persistence across
restarts, visual design, export back to `.docx`/`.pdf`, version history, collaborative editing,
exhaustive test coverage.

Additionally cut by choice, to be stated in the README:
- **PDF parsing** — one format done properly beats two done halfway.
- **Retrieval / embeddings** — unnecessary at this document size.
- **Applying ripple edits automatically** — they are proposed and shown, never written outside the
  selected section. The consultant stays the editor of record.
- **More than two clarification rounds** — beyond that the agent states an assumption instead.

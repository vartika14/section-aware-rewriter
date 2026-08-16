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

## 14. Addendum — Phase 3/4 refinements (2026-08-14)

Written after phases 0–2 shipped and confirmed the whole-document context works — and is dangerous
unaudited (see `docs/status.md`: the phase-2 draft silently turned "no more than twelve" into a
commitment and invented "twelve stakeholder interviews" by pulling a number from section 4 into
section 2). These refinements tighten §4 and §6.4 before Phase 3 is built, so `resolvable_from_document`
is a verified claim rather than a trusted model boolean.

### 14.1 `resolvable_from_document` must be grounded, not trusted

The original §6.4 schema let the audit call assert `resolvable_from_document: bool` with nothing to
check it against. Since DECIDE (§6.2) treats that boolean as license to skip asking the human, an
ungrounded true is the single riskiest failure mode in the whole pipeline — it's a silent wrong
answer dressed as a correct one.

`Finding` gains two fields, required together:

```python
class Finding(BaseModel):
    section_id: str
    quote: str
    kind: Literal["contradiction", "invalidated_premise", "stale_reference"]
    explanation: str
    resolvable_from_document: bool
    deriving_section_id: str | None = None   # which other section supplies the answer
    deriving_quote: str | None = None        # exact quote from that section grounding the derivation
    proposed_fix: str | None
```

`deriving_quote` follows the same grounding logic §6.4 already applies to `quote`: a citation that
can be checked against real text is one that can't be silently hallucinated.

### 14.2 `policy.py` verifies the citation deterministically

No extra model call. `is_resolvable` normalizes whitespace/case and substring-checks both quotes
against the actual section text; any failure — missing fields, an unknown `deriving_section_id`, a
`deriving_quote` that isn't actually in that section — fails closed to "ask":

```python
def is_resolvable(finding: Finding, sections_by_id: dict[str, Section]) -> bool:
    if not finding.resolvable_from_document:
        return False
    if not finding.deriving_section_id or not finding.deriving_quote:
        return False
    section = sections_by_id.get(finding.deriving_section_id)
    if section is None:
        return False
    return normalize(finding.deriving_quote) in normalize(section.text)

blocking = lambda f: f.kind != "stale_reference" and not is_resolvable(f, sections_by_id)
```

This is the function read aloud in the session in place of the bare boolean check in §4 — it's the
same policy, made falsifiable.

### 14.2a The two quotes fail in opposite directions

Both `quote` and `deriving_quote` are substring-verified, but an unverifiable one means something
different in each case, and the safe response is the opposite each time:

| Field | What an unverifiable quote means | Response |
|---|---|---|
| `deriving_quote` | The proposed *resolution* is ungrounded | Fail closed — treat as not resolvable, **ask** |
| `quote` | The *conflict itself* is ungrounded, possibly hallucinated | **Never blocking** — demote to a ripple, marked unverified |

Failing closed on `quote` would mean interrupting a consultant about a conflict that may not exist —
the precise interrupt-fatigue failure §2 warns about. Dropping it silently is also wrong: the
codebase already holds the line that hiding part of a document from the user is the class of bug
this tool exists to prevent (see the `(untitled opening)` decision in the README). So an
unverifiable finding is surfaced as a ripple, flagged `verified: false`, and can never trigger a
question.

Verification is normalized on whitespace and case before comparison, so ordinary reformatting
doesn't read as a hallucination.

### 14.3 Collapsing findings that share an answer

§4 states findings sharing an answer collapse into one question, without saying how "sharing an
answer" is determined. Rule: **group blocking findings by `section_id`** — the other section each
one conflicts with. Findings citing the same section share a root tension and become one question
with options that resolve all of them together (the brief's Example A: a fee finding and a
deliverables finding, both pointing at the pricing section, become one three-option question).
Findings citing different sections become separate groups.

Within the two-round cap (§7): round 1 asks about the first group (by order found), round 2 asks
about the next group if one remains unresolved, and beyond that the agent proceeds and states its
assumption in the result rather than asking a third time.

### 14.4 Question wording stays split between Python and the model

Per the open question in `docs/status.md` §3c: **Python decides whether to ask and builds the
lettered options from the finding group; a separate, narrowly-scoped model call only rephrases that
into natural prose.** The phrasing call cannot alter option keys or branches — it receives them as
fixed input and returns text only. This keeps the graded judgement (ask-or-not, what the branches
are) in testable Python while the question a consultant reads doesn't sound templated.

### 14.5 Two specced behaviours `llm.py` does not yet have

Phase 2's `structured_completion` takes neither a temperature nor a retry, though §10 requires
"schema validation with one retry" and the audit step requires temperature pinned to 0. Both land
in Phase 3, in the one seam every call already passes through:

- **`temperature=0` on the audit call.** An interrupt policy that fires intermittently can be
  neither defended in the session nor tested. The draft call keeps a default temperature; only the
  graded judgement needs determinism.
- **One retry on a schema violation**, then a clear `ModelRefusal` to the UI. Never a silent
  partial result.

### 14.6 What did not change

§3 (taxonomy), §6.1–6.3 (three-step suspendable pipeline, DRAFT/AUDIT separation, whole-document
context), §7 (API shape — `POST /rewrite`, `POST /rewrite/{session_id}/answer`, same discriminated
`status` shapes), §8 (module-level dict of `RewriteSession`), and §10 (error handling) all stand as
originally specced. Phase 2 validated the architecture; it only exposed a gap in how much the audit
step could be trusted.

## 15. Addendum — Phase 4 design (2026-08-16)

Written after phase 3 shipped. The agent now asks its question; nothing consumes the answer. This
addendum specifies the back half of the loop. It amends three earlier passages, all written before
the three branches of §14.4 existed:

- **§8 and the "resume at DRAFT" arrow in §6's diagram** — resume re-enters DRAFT on one branch of
  three, not on all of them (§15.1).
- **§7's `complete` shape** — gains `assumptions` (§15.6).
- **§14.3's round-2 rule** — still correct, but incomplete; an answer can create a conflict as well
  as leave one unasked (§15.4).

### 15.1 Only one branch re-drafts

§8 says resume "re-enters DRAFT with the answer appended as an additional constraint". Applied to
all three branches, that is wrong. The branches are not three flavours of the same instruction —
two of them are the author saying *keep what you showed me*:

| Branch | The author is saying | New text needed |
|---|---|---|
| (a) hold the other section | the other clause is fixed; trim the rewrite to fit it | **yes** |
| (b) make the rewrite, flag the other section | the rewrite is right; I will fix the other clause myself | no |
| (c) make the rewrite, leave the other section | the rewrite is right and I accept the mismatch | no |

Returning to the model on (b) or (c) would risk handing back text different from the text the
author just approved. In an editing tool that is the worst available surprise. So:

```
(a) → DRAFT (+ constraint) → AUDIT → DECIDE      1 model call
(b) → the stored draft; the group's findings become ripples      0 model calls
(c) → the stored draft; the group's findings are dropped         0 model calls
```

`RewriteSession.draft_text` already exists to make (b) and (c) free.

### 15.2 Branch meaning gets a name

The semantics of a branch currently live only inside a label string in `question.BRANCHES`.
Switching on the bare key `"a"` in the resume path would put the meaning in two places and keep it
in neither. One enum, in the module that owns the branches:

```python
class Branch(str, Enum):
    HOLD   = "a"   # hold the other section; reshape the rewrite to fit
    FLAG   = "b"   # make the rewrite; flag the other section
    ACCEPT = "c"   # make the rewrite; leave the other section
```

Keys stay `a`/`b`/`c` in the API. An unrecognised key is rejected at the HTTP boundary.

### 15.3 The HOLD constraint is built in Python, not asked for

The added constraint is generated deterministically from the `FindingGroup`, so what the second
draft is asked to honour can be unit tested:

> *4. Fees and Payment must stand exactly as written. It says "A fixed fee of EUR 48,000 covers the
> scope set out in section 2." Shape the rewrite so this remains true.*

`draft_rewrite` gains `constraints: Sequence[str] = ()`, appended to its user message. Nothing else
about DRAFT changes.

The re-audit is passed the **original instruction only** — not the constraint. If the second draft
failed to honour the held clause, a neutral audit flags it again, which is the correct outcome. An
audit told what the draft was trying to do would be inclined to grant that it succeeded.

### 15.4 Re-audit exactly when the text changed

§14.3 said round 2 draws from the next unasked group. That covers leftovers but misses the more
interesting case: an answer can *create* a conflict that did not exist when the question was asked.
Hold the fee, trim the scope to fit, and the executive summary now promises deliverables the scope
no longer contains.

- **After (a)**, the text is new and unchecked, so it is audited; round 2 comes from the new blocking
  groups.
- **After (b) or (c)**, the text is byte-identical to text already audited. Re-auditing it would
  spend a call to ask the same question of the same words. Round 2 comes from the next unasked group
  of the original decision.

Ripples follow the same rule: replaced from the fresh audit after (a), carried over from the session
after (b) and (c), since ripples describing deleted text are worse than no ripples.

### 15.5 A question is never asked twice

`RewriteSession` gains `asked_section_ids: list[str]`, appended to whenever a question is composed.
A blocking group naming one of them is demoted to a ripple rather than raised again.

This is not hypothetical. Branch (a) can redraft, fail to honour the constraint, and produce the
identical finding — and re-asking a question the author has already answered is a sharper version of
the interrupt fatigue §2 warns about, because it also says the tool did not listen.

### 15.6 The cap, and saying what was assumed

Within `resume()` the order is fixed: record the answer, do the work, then decide whether another
question is allowed. A question may be asked while `len(session.answers) < 2`.

```
answers == []        →  start() asked question 1
answers == ["b"]     →  a second question is allowed
answers == ["b","a"] →  the cap is spent; complete with assumptions
```

Two questions, ever. `answers` is appended **after** any model call returns, so a 502 mid-resume does
not consume a round: the session survives intact and the author can retry.

Blocking groups still outstanding when the cap is spent become plain sentences on the result:

```python
class RewriteComplete(BaseModel):
    ...
    assumptions: list[str] = []   # "Proceeding with the rewrite; 4. Fees and Payment
                                  #  left as it stands."
```

A separate field rather than another ripple, because an assumption is a decision the agent made
*instead of* asking, and burying it among proposed edits would hide exactly the thing §7 promises to
state.

### 15.7 `declined` is a round-1 outcome only

`instruction_applicable` is honoured in `start()` and ignored in `resume()`. Round 1 already
established that the instruction applies to the section; a flip on re-audit is far more likely model
noise than a genuine reversal, and acting on it would discard work the author has already answered
two questions about. The asymmetry is deliberate and stated here so it does not read as an omission.

### 15.8 Where the loop lives

A new module, `app/loop.py`, owns the suspendable run and the session lifecycle:

```python
Outcome = Completed | Asking | Declined

def start(document, *, section_id, instruction) -> Outcome
def resume(session_id, *, option_key) -> Outcome
```

`start()` is phase 3's `/rewrite` body moved unchanged; that step is a pure refactor and the existing
suite must pass untouched. `main.py` returns to being what its docstring claims — validation,
mapping and turning model failures into 502s.

The alternative was leaving both endpoints in `main.py`. Rejected: the branch semantics, the cap and
the assumption text are the phase-4 equivalent of `policy.py`, and logic reachable only through
`TestClient` is logic that does not get tested properly. This is one module and two functions, not a
state machine or a job queue — the run still suspends by returning, exactly as §6 specced.

### 15.9 Edge cases

Named here so they are handled deliberately rather than discovered, per §10:

| Case | Response |
|---|---|
| unknown `session_id` | 404, readable |
| unrecognised `option_key` | 422 |
| answering a session that already finished | 409, "this rewrite has already finished" — the stale-tab case |
| the document is gone from the store | 404, "upload it again" — real, since state is in memory |
| the model fails during a (a) redraft | 502; session intact, round not consumed |
| the redraft still conflicts with the held section | demoted to a ripple, never re-asked (§15.5) |
| the re-audit finds a different section broken | that is round 2 (§15.4) |
| the re-audit finds nothing | complete |
| the cap is spent with groups outstanding | complete, with `assumptions` (§15.6) |

### 15.10 Three phase-3 gaps closed alongside

Small, and each one is in the path phase 4 exercises:

- **`is_resolvable` can ground a resolution in the section being rewritten.** `decide()` receives the
  original sections, including the old text of the section under edit — so a finding claiming "the
  rewritten section already resolves this", quoting text the draft is about to delete, verifies and
  buys silence. `decide()` gains the target section id and refuses to ground anything in it. This is
  a hole in the §14.2 verification story and belongs closed before the loop leans on it harder.
- **Ripples never reach the browser.** The API returns them; `lib/api.ts` has no field for them, so
  they are dropped. Hiding part of a document from the author is the class of bug this tool exists to
  prevent, and it is currently happening in our own front end.
- **`compose_question` takes `instruction` and never uses it**, while its prompt forbids re-asking an
  instruction the model is never shown. Wired in.

### 15.11 Testing

Conventions from phases 0–3 hold: offline, the model substituted at the single `llm.py` seam,
findings hand-built including dishonest ones, `.docx` fixtures built in memory.

- **`tests/test_loop.py`** (new) — branch semantics, cap arithmetic, already-asked suppression,
  assumption text, ripple carry-over versus replacement. No HTTP and no network: this is where the
  phase-4 judgement is defended, the way `test_policy.py` defends phase 3's.
- **`tests/test_api.py`** — every row of §15.9, plus a full two-round path.
- **`tests/test_policy.py`** — a finding grounding its resolution in the section being rewritten.
- **`tests/test_question.py`** — the instruction reaches the prompt.
- **`tests/test_calibration.py`** — one opt-in live case asserting the loop terminates within two
  rounds and never 500s. Outcome only, never wording, per §11.

### 15.12 Build order

Eleven steps, each independently testable and committable.

| # | Step | Exit criterion |
|---|---|---|
| 1 | `Branch` enum; wire `instruction` into `compose_question` | existing question tests pass; instruction appears in the prompt |
| 2 | Self-reference guard in `policy.decide` | a resolution grounded in the rewritten section fails closed |
| 3 | `draft_rewrite(constraints=...)` | the constraint appears in the user message |
| 4 | Refactor: `loop.start()`, `main.py` maps | all existing tests pass unchanged |
| 5 | `loop.resume()` — the three branches | branch tests pass; no cap yet |
| 6 | Cap, assumptions, already-asked suppression | cap tests pass |
| 7 | `POST /rewrite/{session_id}/answer` | §15.9 passes end to end |
| 8 | `api.ts`: response union, `ripples`, `assumptions`, `answerQuestion()` | types compile against the real API |
| 9 | `QuestionPanel` | question and lettered options render; a click posts |
| 10 | `ResultPanel`: ripples, assumptions, `declined` | nothing the backend returns is dropped |
| 11 | Live calibration case; README and `docs/status.md` | phase 4 marked done, honestly |

Steps 1–3 are prep, 4 is a pure refactor, 5–7 are the feature, 8–10 the front end. Roughly two hours
rather than the one estimated in `docs/status.md`: step 10 alone turns a single-state component into
a four-state one.

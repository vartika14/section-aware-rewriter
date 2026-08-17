# Section-aware rewrite agent

Rewrite one section of a document without quietly breaking the rest of it.

> Status: complete, on a simplified design. Upload, parse, rewrite, detect what
> the rewrite breaks, and — at most once — ask a specific question before
> completing. See [the design spec](docs/superpowers/specs/2026-08-17-simplified-agent-design.md)
> for the conflict taxonomy and the interrupt policy, and
> [the status notes](docs/status.md) for what measuring against the real model
> across three different documents changed. An earlier, more elaborate version
> of this design (a two-round clarification loop, silent auto-resolution) is
> kept at [the original spec](docs/superpowers/specs/2026-08-13-section-rewrite-agent-design.md)
> — it measured real things worth knowing, and this version is a deliberate
> simplification of it, not a first draft.

## Running it

Two processes. Python 3.12+ and Node 20+.

**Backend** (from `backend/`):

```bash
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env` and fill in either the Azure block
or `OPENAI_API_KEY`. Then:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload
```

**Front end** (from `frontend/`):

```bash
npm install && npm run dev
```

Open http://localhost:3000.

## Checking it works

```bash
./.venv/bin/python -m pytest tests/ -q
```

90 tests, about three seconds, no network — the model seam is substituted at
`app.llm.structured_completion`. The interrupt policy (`conflicts.py`) and the
suspendable run (`orchestrator.py`) are the bulk of them, tested against
hand-built findings including dishonest ones, because their job is to be right
about whatever the model returns.

The calibration cases call the real model, so they are opt-in — and they run
against **three different documents**, not one, because a design that only
works on the vocabulary of a single proposal has not been shown to generalize:

```bash
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

One case requires the agent to stay **silent** — an instruction that changes no
commitment. Precision matters as much as recall, and that case is what shows the
policy is calibrated rather than merely anxious. One drives the whole
clarification loop and asserts only that it terminates.

Confirm credentials reach the model before building on them:

```bash
./.venv/bin/python -m scripts.smoke_test
```

Generate the sample documents used for development — a consulting proposal, an
internal policy, and a project charter:

```bash
./.venv/bin/python -m scripts.make_sample_docx
./.venv/bin/python -m scripts.make_policy_docx
./.venv/bin/python -m scripts.make_charter_docx
```

## Layout

```
backend/
  app/parsing.py      .docx → sections. The riskiest non-agent code; tested
                       first. Text before the first heading gets a fixed id
                       ("preamble") rather than shifting every real section's
                       number.
  app/rewrite.py       DRAFT: rewrite the section, whole document as context.
                       Also decides whether the instruction applies at all,
                       before a conflict check is ever run.
  app/conflicts.py     DETECT + the whole interrupt policy: find_conflicts()
                       (one model call, with the section-id field constrained
                       to this document's real ids), ground() (the one
                       deterministic safety net — is the quote real, is it
                       actually another section), decide().
  app/question.py      Python builds the three lettered options; the model
                       only phrases them.
  app/orchestrator.py  The suspendable run: start() may return a question;
                       resume()'s return type has no arm for a second one.
  app/llm.py           The single seam every model call passes through.
  app/config.py        Credentials. Azure preferred, plain OpenAI as fallback.
  app/store.py         In-memory state; persistence is out of scope.
  app/main.py          HTTP surface. Validation and mapping, nothing else.
  scripts/             Smoke test and the three sample-document generators.
  tests/               Real .docx fixtures built in memory, never
                       hand-written JSON.
frontend/
  app/page.tsx          Container: holds document and selection state.
  app/components/       UploadPanel, SectionList, InstructionPanel,
                        QuestionPanel, ResultPanel.
  lib/api.ts            Typed calls to the Python API.
```

The rewrite is two model calls and one function that makes the decision. A
third call only runs if you pick the one branch that needs new text:

```
instruction ─→ DRAFT ─→ DETECT ─→ DECIDE ─→ complete + notes
                (llm)   (llm)    (python)   or one question
                  ↑                              ↓
                  └──── only if you answer  ─────┘
                        "hold the other section"
```

## How it decides to interrupt you

DETECT produces evidence; Python decides. The whole policy is `ground()` plus
`decide()` in `conflicts.py` — about 40 lines, replacing what used to be two
files and 391 lines:

```python
def ground(conflicts, sections_by_id, rewritten_id):
    """Keep only conflicts whose quote is real, in a section other than the
    one being rewritten."""
    ...

def decide(conflicts, sections, rewritten_id):
    grounded = ground(conflicts, by_id, rewritten_id)
    blocking = [c for c in grounded if c.blocking]
    if not blocking:
        return Decision(action="complete", notes=to_notes(conflicts, grounded, by_id))
    primary = [c for c in blocking if c.section_id == blocking[0].section_id]
    return Decision(action="ask", asking=primary, notes=to_notes(...))
```

**It does not trust the model's quote, and it trusts the model's judgment.**
Every conflict must quote the clause it claims to conflict with, and that quote
is checked against the real text — an ungrounded conflict is reported, flagged
`verified: false`, but can never become a question. That is the one thing kept
from the earlier, more elaborate policy this design replaces: an unproven
conflict must not interrupt anyone, because that is how a tool like this gets
switched off.

What changed: whether a grounded conflict is worth asking about — `blocking` —
is the model's own judgment, trusted directly, rather than layered under a
label Python second-guesses with a keyword list. The prior design's
`quotes_a_commitment` regex covered money and explicit caps and would have
missed, say, an approval threshold in a policy document with no money language
at all. Trusting `blocking` directly is the room "extra model calls for
conflict detection" bought — and it is proven, not asserted: the calibration
suite runs the same policy against a document that never mentions money at all.

**Only the first blocking section is ever asked about.** Everything else that
round — a second blocking section, or a non-blocking finding — becomes a note
instead of a second question. That single rule is the entire reason the agent
never asks twice: there is nothing to cap, because `decide()` only ever
produces one group to ask about.

## What you can answer, and what each answer does

Two sections disagree, so something has to give. There are exactly three things
that can, which is why the options are generated rather than invented by a
model:

| You pick | What gives | What runs |
|---|---|---|
| **(a)** Hold the other section, shape the rewrite to fit | your section | re-draft under a constraint built from the finding, then re-check the new text |
| **(b)** Make the rewrite, flag the other section | the other section, by your hand | the draft you were shown, returned unchanged; the finding becomes a note |
| **(c)** Make the rewrite, leave the other section | nothing | the draft you were shown, returned unchanged |

**Only (a) goes back to the model.** On (b) and (c) you said *make the
rewrite* — the one in front of you. Re-generating it could hand back something
else, which is the worst surprise an editing tool has to offer. There is a test
that asserts nothing but the absence of a model call on those two branches.

There is no free-text option. The brief names an open prompt as a failure
mode, and a text box quietly hands the judgement back to the human the agent
is supposed to be doing the thinking for. If you have a new number, that is
(b): the agent never writes outside your section anyway.

**At most one question, ever — not a cap, a fact about the return type.**
`orchestrator.resume()` returns `Completed | Declined`. There is no `Asking`
arm to return, so a second interrupt is not a bug the code avoids at runtime;
it is a state the function cannot express. Whatever branch (a)'s re-check
finds is folded into the result's notes instead.

## Decisions worth knowing

**.docx only, not PDF.** Word carries real heading styles, so section
boundaries are read rather than inferred from font sizes and positions. One
format done properly beats two done halfway.

**No retrieval, no embeddings.** A 2–4 page document fits in one context
window, so the whole document is sent on every call. Knowing when not to reach
for RAG is part of the answer.

**No agent framework.** The orchestration is the substance of this
assignment; putting it behind LangChain would hide the judgement rather than
show it.

**Text before the first heading gets a fixed id, not a shifted one.**
`"preamble"`, outside the numbered sequence — kept, never dropped, since
silently hiding part of a document from the agent is exactly the class of bug
this tool exists to prevent, but no longer pushing every real section's number
one further than its heading suggests.

**DRAFT and DETECT are separate calls.** A model asked to write and critique
in one breath rationalises. DETECT is also framed as an anonymous review, with
no hint that it is reading its own output.

**Both calls are pinned to temperature 0, and the retry is nudged off it.**
Pinning only DETECT is not enough, because DETECT's only input is the draft.
The retry on a schema violation is nudged to a small non-zero temperature on
its second attempt — otherwise a deterministic failure fails twice and calls
itself a retry. Even pinned, this reduces variance rather than removing it,
which is why the policy is defended by unit tests rather than golden outputs —
see [the status notes](docs/status.md) for the measured pass rate on the
brief's own worked example.

**Notes are proposed, never applied.** Nothing is written outside the
selected section. The consultant stays the editor of record.

**Section ids are enforced by the schema, not repaired after the fact.** The
response schema for DETECT is built per request, with the section-id field
constrained to a `Literal` over this document's actual ids — a model that
tries to invent one fails schema validation outright, which already retries,
instead of reaching application code as something to guess back into shape.

**Two of the three answers cost no model call at all.** They are the author
approving text they have already read, so there is nothing left to generate —
and nothing left to be non-deterministic about. That is a property of the
design, not a lucky result.

**The interrupt logic lives in `orchestrator.py` and `conflicts.py`, not in
the HTTP handler.** Which branch re-drafts, when to re-check, and the decision
to ask are logic reachable only through an HTTP client is logic that does not
get tested properly.

**Proven against three documents, not one.** A consulting proposal, an
internal remote-work policy with no money language anywhere, and a project
charter. The old design's one document-specific piece — a regex tied to money
vocabulary — would have visibly failed on the second and third; the current
design has nothing document-specific left to fail.

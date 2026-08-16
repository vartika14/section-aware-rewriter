# Section-aware rewrite agent

Rewrite one section of a document without quietly breaking the rest of it.

> Status: phases 0–4 of 5 complete. The loop is closed: upload, pick a section,
> say how it should change, answer the question if one comes back, and see the
> result with everything else the edit touched. See
> [the design spec](docs/superpowers/specs/2026-08-13-section-rewrite-agent-design.md)
> for the conflict taxonomy and the interrupt policy, and
> [the status notes](docs/status.md) for what measuring against the real model
> changed.

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

118 tests, about three seconds, no network — the model seam is substituted. The
interrupt policy and the clarification loop are the bulk of them, tested against
hand-built findings including dishonest ones, because their job is to be right
about whatever the model returns.

The calibration cases do call the real model, so they are opt-in. They assert
only on ask-versus-don't-ask, never on wording:

```bash
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

One of the five requires the agent to stay **silent** — an instruction that
changes no commitment. Precision matters as much as recall, and that case is what
shows the policy is calibrated rather than merely anxious. A fifth drives the
whole loop and asserts only that it terminates within two questions.

Confirm credentials reach the model before building on them:

```bash
./.venv/bin/python -m scripts.smoke_test
```

Generate the sample proposal used for development:

```bash
./.venv/bin/python -m scripts.make_sample_docx
```

## Layout

```
backend/
  app/parsing.py    .docx → sections. The riskiest non-agent code; tested first.
  app/agent.py      DRAFT: rewrite the section, whole document as context.
  app/audit.py      AUDIT: a separate, neutrally framed call — what breaks?
  app/policy.py     DECIDE: the interrupt policy. Pure Python, no model call.
  app/question.py   Python builds the branches; the model only phrases them.
  app/loop.py       The suspendable run: which branch re-drafts, when to audit
                    again, when to stop asking.
  app/llm.py        The single seam every model call passes through.
  app/config.py     Credentials. Azure preferred, plain OpenAI as fallback.
  app/store.py      In-memory state; persistence is out of scope.
  app/main.py       HTTP surface. Validation and mapping, nothing else.
  scripts/          Smoke test and sample-document generator.
  tests/            Real .docx fixtures built in memory, never hand-written JSON.
frontend/
  app/page.tsx      Container: holds document and selection state.
  app/components/   UploadPanel, SectionList, InstructionPanel, QuestionPanel,
                    ResultPanel.
  lib/api.ts        Typed calls to the Python API.
```

The rewrite is two model calls and one function that makes the decision. A third
call phrases the question, when there is one:

```
instruction ─→ DRAFT ─→ AUDIT ─→ DECIDE ─→ complete + ripples
                (llm)   (llm)   (python)   or a question
                  ↑                              ↓
                  └──── only if you answer  ─────┘
                        "hold the other section"
```

## How it decides to interrupt you

The audit produces evidence; Python decides. The rule is one line, and the point
of the design is that it is a line of code rather than a line of prompt:

```python
blocking = kind_is_not_merely_descriptive and is_verified and not is_resolvable
```

**It does not trust the model's answers.** Each finding must quote the clause it
claims to conflict with, and a finding claiming the document already resolves it
must also cite the section and words that do the resolving. Both quotes are
checked against the real text, and they fail in opposite directions on purpose:

| Unverifiable | Means | Response |
|---|---|---|
| the conflict's own quote | the conflict may be invented | never ask — report it, flagged unverified |
| the resolving quote | the fix is ungrounded | ask after all |

Failing closed on the first would mean interrupting a consultant about an
imaginary problem, which is how a tool like this gets switched off.

`kind` is treated the same way. A conflict labelled `stale_reference` is normally
silent, but the label is the model's opinion — measured against the real model, a
fixed fee whose premise had moved came back labelled a stale reference on a third
of runs, which would have walked it silently past the policy. A quote carrying
money or an explicit cap can no longer buy silence with a label.

Findings that land on the same section collapse into one question: two
consequences on one clause are one decision for the author, not two.

## What you can answer, and what each answer does

Two sections disagree, so something has to give. There are exactly three things
that can, which is why the options are generated rather than invented by a model:

| You pick | What gives | What runs |
|---|---|---|
| **(a)** Hold the other section, shape the rewrite to fit | your section | re-draft under a constraint built from the finding, then audit the new text |
| **(b)** Make the rewrite, flag the other section | the other section, by your hand | the draft you were shown, returned unchanged; the finding becomes a ripple |
| **(c)** Make the rewrite, leave the other section | nothing | the draft you were shown, returned unchanged |

**Only (a) goes back to the model.** On (b) and (c) you said *make the rewrite* —
the one in front of you. Re-generating it could hand back something else, which
is the worst surprise an editing tool has to offer.

There is no free-text option. The brief names an open prompt as a failure mode,
and a text box quietly hands the judgement back to the human the agent is
supposed to be doing the thinking for. If you have a new number, that is (b): the
agent never writes outside your section anyway.

**Two questions, ever.** After that it proceeds and says what it assumed, on the
result rather than buried in the ripples. And it never asks about the same
section twice — measured against the real model, holding the fee produced a
second draft whose audit flagged the fee *again*; the policy would have asked,
and the loop demoted it to a ripple instead. Asking a question the author has
already answered says the tool was not listening.

## Decisions worth knowing

**.docx only, not PDF.** Word carries real heading styles, so section boundaries
are read rather than inferred from font sizes and positions. One format done
properly beats two done halfway.

**No retrieval, no embeddings.** A 2–4 page document fits in one context window,
so the whole document is sent on every call. Knowing when not to reach for RAG
is part of the answer.

**No agent framework.** The orchestration is the substance of this assignment;
putting it behind LangChain would hide the judgement rather than show it.

**Text before the first heading is kept**, as `(untitled opening)`, rather than
dropped — silently hiding part of a document from the agent is exactly the class
of bug this tool exists to prevent.

**The draft and the audit are separate calls.** A model asked to write and
critique in one breath rationalises. The audit is also framed as an anonymous
review, with no hint that it is reading its own output.

**Both calls are pinned to temperature 0.** Pinning only the audit is not enough,
because the audit's only input is the draft: an unpinned draft flipped the
brief's own example between asking and staying silent across identical runs. This
reduces variance rather than removing it, which is why the policy is defended by
unit tests rather than golden outputs.

**Ripples are proposed, never applied.** Nothing is written outside the selected
section. The consultant stays the editor of record.

**Two of the three answers cost no model call at all.** They are the author
approving text they have already read, so there is nothing left to generate — and
nothing left to be non-deterministic about. That is a property of the design, not
a lucky result.

**The interrupt logic lives in `loop.py`, not in the HTTP handler.** Which branch
re-drafts, when to audit again and when to stop asking are the phase-4 equivalent
of the interrupt policy, and logic reachable only through an HTTP client is logic
that does not get tested properly.

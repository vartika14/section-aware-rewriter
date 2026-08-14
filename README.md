# Section-aware rewrite agent

Rewrite one section of a document without quietly breaking the rest of it.

> Status: phases 0–3 of 5 complete. Upload, parse, rewrite, audit, and the
> decision to interrupt all work; the API asks its question, and phase 4 is the
> front end rendering it and the answer resuming the rewrite. See
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

83 tests, about three seconds, no network — the model seam is substituted. The
interrupt policy is the bulk of them, tested against hand-built findings
including dishonest ones, because its job is to be right about whatever the model
returns.

The calibration cases do call the real model, so they are opt-in. They assert
only on ask-versus-don't-ask, never on wording:

```bash
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

One of the four requires the agent to stay **silent** — an instruction that
changes no commitment. Precision matters as much as recall, and that case is what
shows the policy is calibrated rather than merely anxious.

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
  app/llm.py        The single seam every model call passes through.
  app/config.py     Credentials. Azure preferred, plain OpenAI as fallback.
  app/store.py      In-memory state; persistence is out of scope.
  app/main.py       HTTP surface.
  scripts/          Smoke test and sample-document generator.
  tests/            Real .docx fixtures built in memory, never hand-written JSON.
frontend/
  app/page.tsx      Container: holds document and selection state.
  app/components/   UploadPanel, SectionList, InstructionPanel, ResultPanel.
  lib/api.ts        Typed calls to the Python API.
```

The rewrite is three model calls and one function that makes the decision:

```
instruction ─→ DRAFT ─→ AUDIT ─→ DECIDE ─→ complete + ripples
                (llm)   (llm)   (python)   or a question
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

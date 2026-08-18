# Status — 17 August 2026

Working notes. The reviewer-facing document is the [README](../README.md); the
reasoning behind the current design is in
[the simplified spec](superpowers/specs/2026-08-17-simplified-agent-design.md),
which supersedes [the original spec](superpowers/specs/2026-08-13-section-rewrite-agent-design.md).

## Why this restart happened

The original design (phases 0–4, documented in the earlier version of this
file and the original spec) worked and was measured against the real model —
but it grew one addendum at a time across four build phases, and
`loop.py` + `policy.py` ended up holding seven interacting concepts (`kind`,
`quotes_a_commitment`, `is_verified`, `is_resolvable`, a deriving-quote
self-reference guard, `asked_section_ids`, a `flagged`/`ripples` split) behind
one decision: should this interrupt the user. That is not a 25-minute
conversation, and it had only ever been tested against one document.

This version cuts to two concepts — a grounded quote, and the model's own
`blocking` judgment — by removing the second clarification round entirely and
removing silent auto-resolution, neither of which the brief required. See the
simplified spec's §0–2 for the full reasoning and the six explicit decisions
that shaped it.

## Where we are

Complete. Every phase of the simplified plan (spec §9, plan
`superpowers/plans/2026-08-17-simplified-agent-restart.md`, 15 tasks) is done:
parsing's preamble fix, `rewrite.py`/`conflicts.py`/`orchestrator.py` replacing
`agent.py`/`audit.py`/`policy.py`/`loop.py`, the frontend rewired onto the new
contract, two more sample documents in different domains, and calibration
tests spanning all three.

90 offline tests passing in about 3 seconds, plus 5 opt-in live calibration
tests. Down from 124 on the prior design — deliberately, since the interrupt
policy itself is a fifth the size and the brief's own guidance is "a few tests
on the parts you consider risky says more than 80% coverage."

## What exists

```
backend/app/
  config.py         Credentials. Azure preferred, plain OpenAI as fallback.
  llm.py            structured_completion() — the one seam every model call
                    passes through. Retry on a schema violation is nudged off
                    a pinned temperature, so a deterministic failure doesn't
                    fail twice and call itself a retry.
  parsing.py        .docx → sections. Text before the first heading gets a
                    fixed id ("preamble"), never a numbered one that shifts
                    everything after it.
  rewrite.py        DRAFT: render_document(), find_section(), draft_section().
                    Decides applicability before a conflict check is spent.
  conflicts.py      DETECT + the whole interrupt policy: find_conflicts()
                    (dynamic per-request schema constraining section ids to
                    this document's real ones), ground(), decide(). ~40 lines
                    for the entire policy, replacing 391.
  question.py       Python builds the three lettered options; the model only
                    phrases them. Retyped from FindingGroup to list[Conflict].
  orchestrator.py   start()/resume(). resume()'s return type has no Asking
                    arm — "at most one question, ever" is enforced by the type
                    checker, not a counter.
  text.py           normalize() — shared by conflicts.py's grounding check.
  store.py          In-memory dict. RewriteSession: 6 fields, down from 9.
  main.py           POST /documents, POST /rewrite, POST /rewrite/{id}/answer.
                    Validation and mapping only.
backend/scripts/
  smoke_test.py            Connectivity check.
  make_sample_docx.py      The Meridian consulting proposal.
  make_policy_docx.py      A remote-work policy — no money vocabulary at all.
  make_charter_docx.py     A project charter — a date and a training
                            commitment, not a fee.
frontend/
  lib/api.ts               Typed calls. answerQuestion() returns
                            RewriteComplete | RewriteDeclined — the frontend's
                            own type checker enforces "cannot ask twice" too.
  app/page.tsx              Container: document, selection, result, error.
  app/components/           UploadPanel, SectionList, InstructionPanel,
                             QuestionPanel, ResultPanel (notes, not
                             ripples+assumptions).
```

## Verified, not assumed

Carried forward from the original design's phase 0 — these facts didn't
change with the restart:

- **The Azure deployment is mislabelled.** It is named `gpt-3` and described
  as GPT-3.5 Turbo, but `response.model` reports `gpt-4.1-mini-2025-04-14`. It
  supports strict structured outputs and carries a 1M-token context window.
  Had the label been accurate, the entire schema-driven approach would have
  needed rethinking — which is exactly why a connectivity check ran before any
  design work.
- **Whole-document context demonstrably works.** Asked to make a scope
  section concrete, the model has repeatedly pulled numbers and constraints
  from other sections it was never asked about directly — the whole document
  reaches the model, and it uses it.

## What the restart measured

Every item here came from running the new pipeline against the real model, on
all three sample documents, not from reasoning about it.

- **The remote-work policy and the charter both ask correctly, reliably.**
  Narrowing the remote-work definition asks about the approval section every
  run. Widening the charter's pilot scope asks about the timeline or training
  commitment every run. Neither document mentions money once — this is the
  direct, working proof that `blocking` (the model's own judgment, trusted
  directly) generalizes where `quotes_a_commitment` (a money/cap regex) would
  not have.
- **The brief's own fee example is the one case with real variance.** Measured
  at roughly 5 passes in 7 runs. Investigated, not assumed: `decide()`
  reliably returns `action="ask"` when handed the grounded, blocking finding
  this instruction should produce (confirmed directly, outside the live
  suite). The miss is `find_conflicts()` occasionally judging the draft's
  added detail — which correctly stays within the document's own interview
  cap — as consistent with the fee rather than as changing what it covers.
  Sharpening `conflicts.py`'s `SYSTEM` prompt with a generalizable principle —
  *a commitment "for" or "assuming" another section is measured against that
  section's specific wording, not just its subject* — measurably improved the
  pass rate (it was failing more often before) without adding a keyword list.
  The prompt gained one bullet, not a taxonomy. The remaining variance is a
  documented property of this deployment: temperature 0 is not
  bit-deterministic on it, which is why the policy is defended by unit tests
  over hand-built findings rather than by asserting a live call always
  behaves identically.
- **The whole loop still terminates within one question**, confirmed on the
  document with a genuine conflict: `start()` asks, `resume(option_key="a")`
  always returns `Completed` or `Declined`, never `Asking` — because the
  function cannot return that.
- **Two multi-round defects survived the original design's own green test
  suite** and were found by hand-tracing paths, not by a failing test — a
  flagged finding could be silently discarded by a later redraft, and a
  refused re-audit could render identically to a clean one. Both were rooted
  in state the simplified design doesn't have any more (a second round to
  manage). Worth saying in the session: a green suite is evidence about the
  paths it covers, nothing more.
- **DRAFT could invent a fact it was never given.** Found by manual testing,
  not by a unit test: asked to "add the name of the account manager" on a
  section where no account manager is named anywhere in the document, it
  wrote in "Jane Doe" — a fabricated name, silently inserted, no different in
  kind from any other silent inconsistency this tool exists to catch. The
  existing `applicable` check only asked "does this topic belong in this
  section," never "do I actually have this fact or am I making it up." Fixed
  with one more rule in `rewrite.py`'s system prompt: an instruction that
  hands over the content to add (*"add a fourth deliverable: a
  change-management plan"*) is fine to write; one that asks for a specific
  real fact — a name, a number, a date — that isn't supplied and doesn't
  appear anywhere else in the document must decline rather than invent one. A
  first, softer wording of this rule did not change the model's behavior at
  all — confirmed by re-running the exact failing case, not assumed fixed
  after editing the prompt. A second, more direct wording (naming the
  fabrication risk explicitly, with matched examples) fixed it, confirmed
  reliable across three fresh runs, with no regression on either a
  content-supplied instruction or a genuinely uncontroversial one, checked the
  same way.

## How to test

From `backend/`, with `.env` filled in:

```bash
./.venv/bin/python -m pytest tests/ -q          # 90 tests, ~3s, no network
./.venv/bin/python -m scripts.smoke_test        # one real Azure call

# The calibration cases, against the real model, across three documents.
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

Run it:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload   # backend
npm run dev                                                        # frontend/
```

Then at http://localhost:3000: upload `backend/sample/meridian-proposal.docx`,
pick **2. Scope of Work**, and enter *"Make this concrete. List the actual
deliverables and drop the hedging."* The agent asks about the fixed fee most
of the time (see the measured variance above); pick any of the three branches
and the rewrite completes. Branch (a) is the one that produces a second draft.

Section ids no longer shift: with the preamble fix, **2. Scope of Work is
now `s2`**, not `s3` — the title line is `preamble`, outside the numbered
sequence.

```bash
DOC=$(curl -s -X POST http://localhost:8000/documents \
  -F "file=@sample/meridian-proposal.docx" | python3 -c "import sys,json;print(json.load(sys.stdin)['document_id'])")
curl -s -X POST http://localhost:8000/rewrite -H "Content-Type: application/json" \
  -d "{\"document_id\":\"$DOC\",\"section_id\":\"s2\",\"instruction\":\"Make this concrete. List the actual deliverables and drop the hedging.\"}"
```

Try the other two documents too — `remote-work-policy.docx` (ask about
narrowing "2. Definitions") and `data-platform-charter.docx` (ask about
widening "2. Scope").

Edge cases worth trying by hand: a `.docx` with no heading styles (expect an
amber warning that the split is a guess), a non-`.docx` file, and an
instruction that makes no sense for the chosen section (expect `status:
declined` with a reason rather than a mangled rewrite).

## Demo order

1. **The true negative.** Tighten the executive summary's prose on the
   proposal → silence. Establish the agent doesn't interrupt before showing
   that it does.
2. **The fee question** on the proposal, or the definition/scope question on
   either of the other two documents — whichever is running reliably that day.
3. **Answer (a)** and watch the second draft come back trimmed to fit.

## Deliberate cuts, to state in the README

- **Notes are proposed, never applied.** The agent writes outside the
  selected section under no circumstances.
- **At most one clarification round, by construction.** `resume()`'s return
  type has no `Asking` arm. The brief's own worked example is a single round
  trip; this design never offers more than that.
- **No silent auto-resolution.** Every conflict either blocks or becomes a
  note. Never required by the brief, and it was the single riskiest code path
  in the design it replaced.
- **No golden-output tests.** Temperature 0 is not bit-deterministic here, so
  the policy is defended by unit tests over hand-built findings, and the live
  suite's variance is measured and documented rather than hidden behind a
  looser assertion.

## Known gaps

- `backend/.env` holds the Azure key in plaintext. Gitignored and verified as
  such, but worth asking Sherpa to rotate it after the assignment.
- Sessions and documents are never evicted from the in-memory store. Correct
  for a single-user demo, wrong for anything else — and worth saying before
  someone asks.
- The brief's own fee example carries genuine, measured, bounded variance
  (~5/7) at temperature 0 on this deployment. Not a code defect — `decide()`
  is confirmed correct given the finding this instruction should produce —
  and worth having the number ready rather than being surprised by a live
  demo that occasionally completes instead of asking.

# Status — 16 August 2026

Working notes. The reviewer-facing document is the [README](../README.md); the
reasoning behind the design is in
[the spec](superpowers/specs/2026-08-13-section-rewrite-agent-design.md).

## Where we are

| Phase | Exit criterion | Status |
|---|---|---|
| 0 · Azure smoke test | A populated Pydantic object from a real call | **done** |
| 1 · Upload → parse → sections | A `.docx` dropped in the browser lists its headings | **done** |
| 2 · Naive rewrite | Select a section, type an instruction, see new text | **done** |
| 3 · Audit + decide | Structured `Finding[]`; pure-Python ask/don't-ask | **done** |
| 4 · Clarification loop | Question renders, option clicked, rewrite completes | **done** |
| 5 · Edges, fixtures, README | Fixture cases incl. a true negative; README | next |

Roughly 6.5 hours spent of the 4–8 hour timebox. 124 offline tests passing in
about 3 seconds, plus 5 opt-in calibration tests against the real model.

The loop is closed end to end: upload, pick a section, instruct, get a question,
answer it, and see the result — with ripples and any stated assumptions. What
remains for phase 5 is the sample document deserving a pass in your own words,
and a last read of the reviewer-facing docs.

## What exists

```
backend/app/
  config.py     Credentials. Azure preferred, plain OpenAI as fallback.
  llm.py        structured_completion() — the one seam every model call passes
                through, and therefore the only thing tests substitute.
  parsing.py    .docx → sections. Heading styles first, blank-line blocks as a
                flagged fallback. Keeps text that precedes the first heading.
  agent.py      render_document() + draft_rewrite(). Whole document as context,
                target section marked [REWRITE].
  audit.py      Finding/AuditResult + audit_rewrite(). The second, neutrally
                framed model call, plus id repair on what it returns.
  policy.py     The interrupt policy. Pure Python, no model call, 32 tests.
  question.py   Python builds the branches; the model only phrases them.
  loop.py       The suspendable run. Which branch re-drafts, when to audit
                again, when to stop asking. No HTTP, so it is tested directly.
  text.py       normalize() — shared by the audit boundary and the policy.
  store.py      In-memory dict. Persistence is out of scope per the brief.
  main.py       POST /documents, POST /rewrite, POST /rewrite/{id}/answer.
                Validation and mapping only; the run lives in loop.py.
backend/scripts/
  smoke_test.py        Phase 0 connectivity check.
  make_sample_docx.py  Generates the Meridian proposal used for development.
frontend/
  lib/api.ts           Typed calls; the only place fetch lives.
  app/page.tsx         Container: document, selection, result, error state.
  app/components/      UploadPanel, SectionList, InstructionPanel,
                       QuestionPanel, ResultPanel.
```

## Verified, not assumed

- **The Azure deployment is mislabelled.** It is named `gpt-3` and described as
  GPT-3.5 Turbo, but `response.model` reports `gpt-4.1-mini-2025-04-14`. It
  supports strict structured outputs and carries a 1M-token context window. Had
  the label been accurate, the entire schema-driven approach would have needed
  rethinking — which is exactly why phase 0 ran first.
- **Whole-document context demonstrably works.** Asked to make section 2
  concrete, the model wrote "twelve stakeholder interviews". That number appears
  nowhere in section 2 — it comes from section 4's fee clause. The model read
  the whole document.
- **And phase 2 is exactly as dangerous as the brief says.** In the same rewrite
  it silently (a) converted section 4's cap of "no more than twelve" into a
  commitment to twelve, (b) named three deliverables under a fixed fee that
  cites section 2 by reference, and (c) introduced "platform optimization",
  which leans on section 5's exclusion of implementation work. It reported none
  of it. Keep that before/after for the session.

## What phase 3 measured, and what it changed

Every item here came from running the pipeline against the real model on the
sample proposal, not from reasoning about it. All four are worth raising in the
session, because each one is a case of the model quietly defeating the design.

- **The model returned `"4. Fees and Payment (s5)"` as a section id.** Nothing
  matched it, so every finding failed verification, was demoted to an unverified
  ripple, and the agent asked nothing at all. The clarification loop was dead and
  the endpoint still returned `200 complete`. Fixed by delimiting the id in the
  rendered document (`## [s5] heading`), saying so in the prompt, and repairing
  unrecognised ids at the audit boundary. Repair is safe precisely because the
  quote is verified separately afterwards: a repair to the wrong section makes
  the quote stop matching, which is the correct outcome.
- **The model called a fixed-fee conflict a `stale_reference` on a third of
  runs**, which routed it straight past the policy — `kind` was blanket-trusted.
  The sharper prompt helped; it did not fix it. What fixed it was treating `kind`
  as an opinion: a quote carrying money or an explicit cap cannot buy silence by
  being labelled a description. `policy.quotes_a_commitment` is deliberately
  narrow — money and caps only, no dates — because widening it costs precision.
- **It also set `resolvable_from_document: true` by reading a cross-reference as
  a resolution.** "The fee assumes the scope set out in section 2" is the reason
  the conflict exists, not the answer to it. The prompt now says so explicitly,
  and the citation requirement catches what the prompt misses.
- **Temperature 0 on the audit alone was not enough**, because the audit's only
  input is the draft. An unpinned draft flipped the brief's own example between
  asking and staying silent across identical runs. Both calls are pinned now.
  Note that this reduces variance rather than eliminating it: temperature 0 on
  this deployment is not bit-deterministic, which is the honest reason the
  policy is defended by unit tests rather than by golden outputs.

The thing to demo: on two of the nine measured runs the model both mislabelled
the kind *and* claimed the document resolved it — two independent paths to
silence — and the Python policy overrode both. That is the argument for keeping
the decision out of the prompt.

## What phase 4 measured

Run against the real model on the sample proposal, `2. Scope of Work`, with
*"Make this concrete. List the actual deliverables and drop the hedging."*

- **Round 1 asked about the fee**, as phase 3 did — the fee assumes the scope in
  section 2 and caps interviews at twelve.
- **Branch (a) honoured its constraint.** The second draft came back with
  "interview up to twelve key stakeholders", down from a first draft that had
  named three deliverables and no cap. The constraint is built in Python from the
  finding group, so what the redraft was held to is a string a test can read.
- **The re-audit flagged the same section again, and the policy would have asked
  a second time.** Instrumented, `decide` on the second draft returned
  `action="ask"` with `groups=["s5"]` — the fee section, all over again. What
  stopped it was the loop's own rule, not the policy: `s5` was already in
  `asked_section_ids`, so it was demoted to a ripple. **This is the thing to
  demo.** Without that rule the agent asks the author the same question twice
  in a row, which reads as not having listened.
- **The model labelled that repeat finding `stale_reference`** — the same
  mislabelling phase 3 measured, on the same clause, still happening. It did not
  matter, because the quote carries the word "fee" and `quotes_a_commitment`
  refuses to let a label buy silence. Two independent guards catching the same
  model habit is worth saying out loud.

Note what did *not* need measuring: branches (b) and (c) make no model call at
all, so there is nothing to be non-deterministic about. That is a property of the
design rather than a lucky result.

Two defects found afterwards by walking multi-round paths by hand, both from one
cause — `resume` held ripples in a single list that branch (a) overwrote from the
fresh audit:

- **An explicit flag was discarded.** Answer "flag the fees" in round one, "hold
  the timeline" in round two, and the fee flag vanished. Replacing what the
  *audit* found is right, since it describes a draft that no longer exists.
  Replacing what the *author* asked for is the tool not listening. `ripples` and
  `flagged` are now separate on the session for exactly that reason.
- **A refused re-audit reported silence.** `instruction_applicable: false` on the
  re-check produced an empty ripple list, so "I refused to look" rendered
  identically to "I looked and found nothing" — this project's own thesis
  failing inside the project. A refused re-check now keeps round one's findings
  and says on the result that it could not re-check.

Worth raising unprompted: both were found by tracing paths no single test
covered, not by a failing test. The suite was green throughout.

## How to test

From `backend/`, with `.env` filled in:

```bash
./.venv/bin/python -m pytest tests/ -q          # 124 tests, ~3s, no network
./.venv/bin/python -m scripts.smoke_test        # one real Azure call

# The calibration cases, against the real model. Opt-in: ~23s and real tokens.
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

Run it:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload   # backend
npm run dev                                                        # frontend/
```

Then at http://localhost:3000: upload `backend/sample/meridian-proposal.docx`,
pick **2. Scope of Work**, and enter *"Make this concrete. List the actual
deliverables and drop the hedging."* The agent asks about the fixed fee; pick any
of the three branches and the rewrite completes. Branch (a) is the one that
produces a second draft.

Backend only, without the UI. Note the ids: the sample's title line takes `s1` as
an untitled opening, so **2. Scope of Work is `s3`** and 4. Fees is `s5`. Getting
this wrong silently rewrites the wrong section — it briefly did exactly that to
three of the calibration tests, which now look sections up by heading instead.

```bash
DOC=$(curl -s -X POST http://localhost:8000/documents \
  -F "file=@sample/meridian-proposal.docx" | python3 -c "import sys,json;print(json.load(sys.stdin)['document_id'])")
curl -s -X POST http://localhost:8000/rewrite -H "Content-Type: application/json" \
  -d "{\"document_id\":\"$DOC\",\"section_id\":\"s3\",\"instruction\":\"Make this concrete. List the actual deliverables and drop the hedging.\"}"
```

Edge cases worth trying by hand: a `.docx` with no heading styles (expect an
amber warning that the split is a guess), a non-`.docx` file, and an instruction
that makes no sense for the chosen section (expect `status: declined` with a
reason rather than a mangled rewrite).

## How phase 4 was built

Eleven commits, spec at `superpowers/specs/…§15`, plan at
`superpowers/plans/2026-08-16-phase-4-clarification-loop.md`. The shape worth
knowing:

- **Only branch (a) returns to the model.** "Hold that section" is the author
  changing their mind about the rewrite. "Flag it" and "leave it" are the author
  approving the draft they were shown, so those return `session.draft_text`
  untouched — going back to the model there could hand back different text than
  the one just accepted. `test_flagging_calls_the_model_not_at_all` is that rule
  in executable form.
- **Re-audit follows the same rule:** audit exactly when the text changed.
- **`loop.py` owns the run**, `main.py` owns HTTP. The extraction was a separate
  commit whose exit criterion was that no test file changed.
- **`declined` is a round-1 outcome only.** A flipped `instruction_applicable` on
  re-audit is more likely model noise than a real reversal, and acting on it
  would discard work the author has already answered a question about.

## Phase 5 — what is left

- The sample proposal is generated by a script. The brief says choosing a
  document that makes the conflict problem visible is part of the exercise, so it
  deserves a pass in your own words.
- A last read of the README as a reviewer would meet it.
- Rehearse the demo: the true negative first, then the fee question, then branch
  (a) and the repeat-finding suppression.

## Deliberate cuts, to state in the README

- **Ripples are proposed, never applied.** The agent writes outside the selected
  section under no circumstances; the consultant stays the editor of record.
- **`quotes_a_commitment` is a word list, not a model call.** It covers money and
  explicit caps and misses, say, a delivery date written in prose. A second model
  call would catch more and be less defensible; the trade is deliberate and the
  function is three lines to read.
- **No golden-output tests.** Temperature 0 is not bit-deterministic here, so the
  policy is defended by unit tests over hand-built findings and the live suite
  asserts only on the ask/don't-ask outcome, never on wording.

## Known gaps

- `backend/.env` holds the Azure key in plaintext. Gitignored and verified as
  such, but worth asking Sherpa to rotate it after the assignment.
- Sessions and documents are never evicted from the in-memory store. Correct for
  a single-user demo, wrong for anything else — and worth saying before someone
  asks.
- Section ids are positional, so a document whose first line is a bare title
  shifts every numbered section by one. Correct, but a sharp edge — the sample
  document has exactly this shape, and it silently misaimed three calibration
  tests before they were changed to look sections up by heading.
- `quotes_a_commitment` is a regex over money and cap phrases. It would not
  catch "delivered before 1 October" written as prose, so a mislabelled
  `stale_reference` on a bare date could still slip through the policy.

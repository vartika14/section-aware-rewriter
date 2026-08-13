# Status — 13 August 2026

Working notes. The reviewer-facing document is the [README](../README.md); the
reasoning behind the design is in
[the spec](superpowers/specs/2026-08-13-section-rewrite-agent-design.md).

## Where we are

| Phase | Exit criterion | Status |
|---|---|---|
| 0 · Azure smoke test | A populated Pydantic object from a real call | **done** |
| 1 · Upload → parse → sections | A `.docx` dropped in the browser lists its headings | **done** |
| 2 · Naive rewrite | Select a section, type an instruction, see new text | **done** |
| 3 · Audit + decide | Structured `Finding[]`; pure-Python ask/don't-ask | next |
| 4 · Clarification loop | Question renders, option clicked, rewrite completes | — |
| 5 · Edges, fixtures, README | Fixture cases incl. a true negative; README | — |

Roughly 2.5 hours spent of the 4–8 hour timebox. Three commits. 20 tests passing.

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
  store.py      In-memory dict. Persistence is out of scope per the brief.
  main.py       POST /documents, POST /rewrite.
backend/scripts/
  smoke_test.py        Phase 0 connectivity check.
  make_sample_docx.py  Generates the Meridian proposal used for development.
frontend/
  lib/api.ts           Typed calls; the only place fetch lives.
  app/page.tsx         Container: document, selection, result, error state.
  app/components/      UploadPanel, SectionList, InstructionPanel, ResultPanel.
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

## How to test

From `backend/`, with `.env` filled in:

```bash
./.venv/bin/python -m pytest tests/ -q          # 20 tests, ~3s, no network
./.venv/bin/python -m scripts.smoke_test        # one real Azure call
```

Run it:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload   # backend
npm run dev                                                        # frontend/
```

Then at http://localhost:3000: upload `backend/sample/meridian-proposal.docx`,
pick **2. Scope of Work**, and enter *"Make this concrete. List the actual
deliverables and drop the hedging."*

Backend only, without the UI:

```bash
DOC=$(curl -s -X POST http://localhost:8000/documents \
  -F "file=@sample/meridian-proposal.docx" | python3 -c "import sys,json;print(json.load(sys.stdin)['document_id'])")
curl -s -X POST http://localhost:8000/rewrite -H "Content-Type: application/json" \
  -d "{\"document_id\":\"$DOC\",\"section_id\":\"s3\",\"instruction\":\"Make this concrete.\"}"
```

Edge cases worth trying by hand: a `.docx` with no heading styles (expect an
amber warning that the split is a guess), a non-`.docx` file, and an instruction
that makes no sense for the chosen section — the last one is not handled yet and
is phase 3 work.

## Phase 3 — the assignment

Two hours. Three deliverables matching the three things Sherpa said the session
would be about.

### 3a. Detect — `app/audit.py`

A second model call, separate from the draft. Framed neutrally: *here is a
section, here is a proposed replacement, here is the rest of the document, what
breaks?* — with no hint that it is reviewing its own output, because a model
asked to write and critique in one breath rationalises.

Returns `AuditResult` (see spec §6.4): `instruction_applicable` plus a list of
`Finding`, each carrying a `quote` from the conflicting section, a `kind`, and
`resolvable_from_document`.

Two decisions to make here: **pin temperature to 0**, because an interrupt
policy that fires intermittently cannot be defended or tested; and **retry once**
on a schema violation before surfacing an error.

### 3b. Decide — `app/policy.py`

Pure Python. No model call. This is the part that gets read aloud in the session,
so it has to be legible:

```
blocking = kind != "stale_reference" and not resolvable_from_document
```

Plus collapsing findings that share an answer into a single question — the
Example A case, where "does the fee still hold" and "is a roadmap implementation"
have one answer between them.

Being deterministic, it can be unit tested exhaustively against hand-built
`Finding` lists, fast and without the network.

### 3c. Word the question

An open decision. Either template the question from the findings
deterministically — defensible and testable, but stilted — or use a third model
call for phrasing only.

Recommendation: **Python decides whether to ask and what the branches are; the
model only handles wording.** That keeps the graded judgement in testable code
while the output still reads like a colleague wrote it.

### 3d. Prove it is calibrated

A small set of fixture cases run against the real model, gated behind an env var
so the default suite stays offline and fast:

1. "Make the scope concrete" → must ask about the fixed fee.
2. "Add a fourth phase" → must ask about the fee, must *fix* the instalment
   count, must stay quiet about the quarter promise.
3. "Interview all eighteen system owners" → must ask; section 4 caps it at twelve.
4. **"Make the executive summary more direct, cut the hedging" → must stay
   silent.** The true negative. Precision matters as much as recall, and this is
   the case that proves the policy is calibrated rather than merely paranoid.

## Known gaps

- `backend/.env` holds the Azure key in plaintext. Gitignored and verified as
  such, but worth asking Sherpa to rotate it after the assignment.
- The sample proposal is generated by a script. It is a starting point — the
  brief says choosing a document that makes the conflict problem visible is part
  of the exercise, so it deserves a pass in your own words.
- The README does not yet explain conflict detection or the interrupt policy.
  That is phase 5, and the spec already holds the raw material.
- Nothing yet handles an instruction that makes no sense for the selected
  section. The schema field exists in the spec; the code lands in phase 3.

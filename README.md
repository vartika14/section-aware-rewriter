# Section-aware rewrite agent

Rewrite one section of a document without quietly breaking the rest of it.

> Status: phases 0–1 of 5 complete (upload → parse → sections). The agent itself
> lands in phases 2–4. See
> [the design spec](docs/superpowers/specs/2026-08-13-section-rewrite-agent-design.md)
> for the conflict taxonomy, the interrupt policy, and the build order.

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
  app/llm.py        The single seam every model call passes through.
  app/config.py     Credentials. Azure preferred, plain OpenAI as fallback.
  app/store.py      In-memory state; persistence is out of scope.
  app/main.py       HTTP surface.
  scripts/          Smoke test and sample-document generator.
  tests/            Real .docx fixtures built in memory, never hand-written JSON.
frontend/
  app/page.tsx      Container: holds document and selection state.
  app/components/   UploadPanel, SectionList.
  lib/api.ts        Typed calls to the Python API.
```

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

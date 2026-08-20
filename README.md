# Section-Aware Rewrite Agent

A small web app for editing one section of a Word document without
accidentally breaking the rest of it.

## What it does

Upload a `.docx`, pick one section — say, "Scope of Work" or "Fees" — and
describe the change you want in plain English. The app rewrites that section.

Before it commits to the change, it checks the rest of the document for
anything that rewrite would quietly break: a fee that assumed the old scope, a timeline that assumed the old number of phases, a paragraph that refers back to wording that no longer exists. If it finds something only you can decide, it stops and asks — showing the exact section and words at stake, not a vague warning. Nothing outside the section you picked is ever changed without you seeing it first.

Once you're happy with your edits, you download a real `.docx` with your
changes applied and everything else exactly as it was.

## Tech stack

- **Backend:** Python, FastAPI, Pydantic (for validating data in and out),
  `python-docx` (for reading and writing Word files).
- **Frontend:** Next.js and React, written in TypeScript, styled with
  Tailwind.
- **AI:** Azure OpenAI, with plain OpenAI as a fallback. Every AI response
  is requested as structured, validated data — never free text the app then
  has to parse and hope is correct.
- **Storage:** none. Everything lives in memory for the life of the server
  process. This is a working prototype, not a deployed service — there's no
  database and no user accounts.

## How it works, briefly

Two separate AI calls do the thinking:

1. **Write the section** — shown the whole document with your chosen
   section marked, the AI writes the new text for that section only.
2. **Check for conflicts** — a second, separate AI call reviews that new
   text against the rest of the document and reports anything it might
   break elsewhere.

Everything after that — deciding whether a finding is serious enough to
interrupt you, building the question you see, remembering which edits
you've already accepted — is ordinary Python, not AI. Keeping that decision out of the AI's hands is what makes it consistent and testable.

If a rewrite affects more than one other section, you see and answer all of them together, in one screen — not one question now and a surprise later.
For each one, you choose to hold that section as written (and reshape your rewrite to fit), flag it for your own review later, or accept the mismatch and move on.

## Running it locally

You'll need Python 3.12+, Node 20+, and an Azure OpenAI or OpenAI API key.

**1. Start the backend**

```bash
cd backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
```

Open `.env` and fill in either the Azure block or `OPENAI_API_KEY`. Keys
must be base64-encoded rather than pasted in raw — encode yours with:

```bash
python3 -c "import base64; print(base64.b64encode(b'YOUR_KEY').decode())"
```

Then start the server:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000 --reload
```

**2. Start the frontend**

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**, upload a `.docx`, and try it.

## Running the tests

```bash
cd backend
./.venv/bin/python -m pytest tests/ -q
```

These run in a couple of seconds with no network calls — the AI is swapped
out for a fake response in tests, so what's actually being checked is the app's own logic: when it decides to interrupt, how it builds the question, how it applies edits.

A separate, opt-in suite calls the real AI model against sample documents, to confirm the interrupt behavior holds up beyond hand-picked test cases:

```bash
RUN_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_calibration.py -q
```

## A quick tour of the code

```
backend/app/
  parsing.py       Reads an uploaded .docx into a list of sections.
  rewrite.py        Writes the new text for one section (1st AI call).
  conflicts.py      Checks that text against the rest of the document
                     (2nd AI call), and decides what's worth asking about.
  question.py       Turns that decision into a question with answer options.
  orchestrator.py   Runs one rewrite start to finish, pausing for a
                     question if one is needed.
  store.py          Keeps uploaded documents and paused rewrites in memory.
  export.py         Rebuilds a real .docx from the edited sections.
  main.py           The HTTP API the frontend talks to.

frontend/app/
  page.tsx           Holds the app's state: which document, which
                      section, which edits have been kept.
  components/        Upload screen, section picker, instruction box,
                      question screen, result screen.
```

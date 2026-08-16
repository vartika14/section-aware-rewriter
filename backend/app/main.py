"""HTTP surface.

The browser talks to this directly — there is no Next.js proxy layer, so CORS
is enabled for the dev front end.
"""

from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, field_validator

from . import loop, store
from .llm import ModelRefusal
from .parsing import Section, UnparseableDocument, parse_docx
from .policy import Ripple
from .question import Branch, Option

app = FastAPI(title="Section-aware rewrite agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class UploadResponse(BaseModel):
    document_id: str
    sections: list[Section]
    headings_detected: bool


@app.post("/documents", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")

    try:
        parsed = parse_docx(await file.read())
    except UnparseableDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UploadResponse(
        document_id=store.save_document(parsed),
        sections=parsed.sections,
        headings_detected=parsed.headings_detected,
    )


class RewriteRequest(BaseModel):
    document_id: str
    section_id: str
    instruction: str

    @field_validator("instruction")
    @classmethod
    def instruction_must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Instruction must not be empty.")
        return value.strip()


class AnswerRequest(BaseModel):
    option_key: str

    @field_validator("option_key")
    @classmethod
    def must_be_a_branch(cls, value: str) -> str:
        """Reject at the boundary rather than deep in the loop, so a bad key is a
        422 about the request instead of a 500 about a ValueError."""
        try:
            Branch(value)
        except ValueError as exc:
            raise ValueError("option_key must be one of: a, b, c.") from exc
        return value


class RewriteComplete(BaseModel):
    """The rewrite stands. `ripples` are the consequences the policy judged not
    worth interrupting for — shown so the consultant can act on them by hand.
    `assumptions` are what the agent decided once it had spent its two questions,
    stated rather than buried."""

    status: Literal["complete"] = "complete"
    section_id: str
    old_text: str
    new_text: str
    ripples: list[Ripple] = []
    assumptions: list[str] = []


class RewriteNeedsClarification(BaseModel):
    """The rewrite is suspended until the user picks an option."""

    status: Literal["needs_clarification"] = "needs_clarification"
    session_id: str
    section_id: str
    question: str
    options: list[Option]


class RewriteDeclined(BaseModel):
    """The instruction made no sense for this section, so nothing was written.

    Declining is a result, not an error: mangling the section confidently would
    be far worse than saying so.
    """

    status: Literal["declined"] = "declined"
    section_id: str
    reason: str


RewriteResponse = RewriteComplete | RewriteNeedsClarification | RewriteDeclined


def _to_response(outcome: loop.Outcome) -> RewriteResponse:
    """One mapper, so both endpoints answer in the same shapes."""
    if isinstance(outcome, loop.Declined):
        return RewriteDeclined(section_id=outcome.section_id, reason=outcome.reason)
    if isinstance(outcome, loop.Asking):
        return RewriteNeedsClarification(
            session_id=outcome.session_id,
            section_id=outcome.section_id,
            question=outcome.question.text,
            options=outcome.question.options,
        )
    return RewriteComplete(
        section_id=outcome.section_id,
        old_text=outcome.old_text,
        new_text=outcome.new_text,
        ripples=outcome.ripples,
        assumptions=outcome.assumptions,
    )


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest) -> RewriteResponse:
    try:
        outcome = loop.start(
            request.document_id,
            section_id=request.section_id,
            instruction=request.instruction,
        )
    except loop.UnknownDocument as exc:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        ) from exc
    except loop.UnknownSection as exc:
        raise HTTPException(
            status_code=404, detail="No section with that id in this document."
        ) from exc
    except (ModelRefusal, OpenAIError) as exc:
        # A refusal, a content filter or a transport error is an expected
        # operating condition for this app, not a crash. Say so plainly.
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    return _to_response(outcome)


@app.post("/rewrite/{session_id}/answer", response_model=RewriteResponse)
async def answer(session_id: str, request: AnswerRequest) -> RewriteResponse:
    """Resume a suspended rewrite. Same three shapes as `/rewrite`, so the front
    end renders a second question exactly as it rendered the first."""
    try:
        outcome = loop.resume(session_id, option_key=request.option_key)
    except loop.UnknownSession as exc:
        raise HTTPException(
            status_code=404,
            detail="No rewrite session with that id — start the rewrite again.",
        ) from exc
    except loop.UnknownDocument as exc:
        # The session outlived its document, which an in-memory store makes
        # possible across a restart. Say which thing is missing.
        raise HTTPException(
            status_code=404,
            detail="The document for this rewrite is gone — upload it again.",
        ) from exc
    except loop.SessionFinished as exc:
        raise HTTPException(
            status_code=409, detail="This rewrite has already finished."
        ) from exc
    except (ModelRefusal, OpenAIError) as exc:
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    return _to_response(outcome)

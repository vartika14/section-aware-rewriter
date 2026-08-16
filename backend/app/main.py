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
from .question import Option

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

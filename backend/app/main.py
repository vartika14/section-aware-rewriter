"""HTTP surface.

The browser talks to this directly — there is no Next.js proxy layer, so CORS
is enabled for the dev front end.
"""

from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, field_validator

from . import store
from .agent import draft_rewrite, find_section
from .audit import audit_rewrite
from .llm import ModelRefusal
from .parsing import Section, UnparseableDocument, parse_docx
from .policy import Ripple, decide
from .question import Option, compose_question

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
    worth interrupting for — shown so the consultant can act on them by hand."""

    status: Literal["complete"] = "complete"
    section_id: str
    old_text: str
    new_text: str
    ripples: list[Ripple] = []


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


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest) -> RewriteResponse:
    document = store.get_document(request.document_id)
    if document is None:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        )

    try:
        section = find_section(document.sections, request.section_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="No section with that id in this document."
        ) from exc

    try:
        draft = draft_rewrite(
            sections=document.sections,
            section_id=request.section_id,
            instruction=request.instruction,
        )
        audit = audit_rewrite(
            sections=document.sections,
            section_id=request.section_id,
            instruction=request.instruction,
            new_text=draft.new_text,
        )
    except (ModelRefusal, OpenAIError) as exc:
        # A refusal, a content filter or a transport error is an expected
        # operating condition for this app, not a crash. Say so plainly.
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    decision = decide(
        audit, document.sections, rewritten_section_id=request.section_id
    )

    if decision.action == "decline":
        return RewriteDeclined(section_id=section.id, reason=decision.reason or "")

    if decision.action == "complete":
        return RewriteComplete(
            section_id=section.id,
            old_text=section.text,
            new_text=draft.new_text,
            ripples=decision.ripples,
        )

    # Suspend. One question per round, so the first group is asked now and any
    # others wait — a human asked four questions stops reading at the second.
    question = compose_question(
        decision.groups[0],
        sections=document.sections,
        instruction=request.instruction,
    )
    session_id = store.save_session(
        store.RewriteSession(
            document_id=request.document_id,
            section_id=request.section_id,
            instruction=request.instruction,
            draft_text=draft.new_text,
            groups=decision.groups,
            ripples=decision.ripples,
        )
    )

    return RewriteNeedsClarification(
        session_id=session_id,
        section_id=section.id,
        question=question.text,
        options=question.options,
    )

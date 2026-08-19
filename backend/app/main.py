"""The HTTP API. The browser calls these routes directly — no proxy layer —
so CORS is enabled for the frontend's dev server.
"""

from typing import Literal

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, field_validator

from . import orchestrator, store
from .conflicts import Note
from .export import build_docx
from .llm import ModelRefusal
from .parsing import Section, UnparseableDocument, parse_docx
from .question import Branch, QuestionGroup
from .rewrite import overlay_texts

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
    current_texts: dict[str, str] = {}

    @field_validator("instruction")
    @classmethod
    def instruction_must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Instruction must not be empty.")
        return value.strip()


class AnswerRequest(BaseModel):
    """One lettered choice per section id, e.g. `{"s4": "a", "s1": "b"}`."""

    choices: dict[str, str]

    @field_validator("choices")
    @classmethod
    def values_must_be_branches(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject a bad letter here, as a clean 422 — before it can become a
        crash deeper in the code. Checking that `choices` covers exactly the
        sections being asked about happens in `orchestrator.resume()`
        instead, since that needs the session, which isn't available here."""
        for key in value.values():
            try:
                Branch(key)
            except ValueError as exc:
                raise ValueError("Each choice must be one of: a, b, c.") from exc
        return value


class RewriteComplete(BaseModel):
    """The rewrite is done. `notes` are things noticed elsewhere in the
    document but not applied — shown so the author can act on them by hand."""

    status: Literal["complete"] = "complete"
    section_id: str
    old_text: str
    new_text: str
    notes: list[Note] = []


class RewriteNeedsClarification(BaseModel):
    """The rewrite is paused until the author answers every row in `groups`
    — usually one row, sometimes more if several sections are affected."""

    status: Literal["needs_clarification"] = "needs_clarification"
    session_id: str
    section_id: str
    groups: list[QuestionGroup]


class RewriteDeclined(BaseModel):
    """The instruction didn't apply to this section, so nothing was written.
    This is a normal result, not an error."""

    status: Literal["declined"] = "declined"
    section_id: str
    reason: str


RewriteResponse = RewriteComplete | RewriteNeedsClarification | RewriteDeclined


def _to_response(outcome: orchestrator.Outcome) -> RewriteResponse:
    """One mapper, so both endpoints answer in the same shapes."""
    if isinstance(outcome, orchestrator.Declined):
        return RewriteDeclined(section_id=outcome.section_id, reason=outcome.reason)
    if isinstance(outcome, orchestrator.Asking):
        return RewriteNeedsClarification(
            session_id=outcome.session_id,
            section_id=outcome.section_id,
            groups=outcome.question.groups,
        )
    return RewriteComplete(
        section_id=outcome.section_id,
        old_text=outcome.old_text,
        new_text=outcome.new_text,
        notes=outcome.notes,
    )


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest) -> RewriteResponse:
    try:
        outcome = orchestrator.start(
            request.document_id,
            section_id=request.section_id,
            instruction=request.instruction,
            current_texts=request.current_texts,
        )
    except orchestrator.UnknownDocument as exc:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        ) from exc
    except orchestrator.UnknownSection as exc:
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
    """Resume a paused rewrite with the author's answers. Returns the same
    response shapes as `/rewrite`, though in practice this can only come
    back complete or declined — never a second question."""
    try:
        outcome = orchestrator.resume(session_id, choices=request.choices)
    except orchestrator.UnknownSession as exc:
        raise HTTPException(
            status_code=404,
            detail="No rewrite session with that id — start the rewrite again.",
        ) from exc
    except orchestrator.UnknownDocument as exc:
        # The session outlived its document, which an in-memory store makes
        # possible across a restart. Say which thing is missing.
        raise HTTPException(
            status_code=404,
            detail="The document for this rewrite is gone — upload it again.",
        ) from exc
    except orchestrator.SessionFinished as exc:
        raise HTTPException(
            status_code=409, detail="This rewrite has already finished."
        ) from exc
    except orchestrator.AnswerMismatch as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ModelRefusal, OpenAIError) as exc:
        raise HTTPException(
            status_code=502, detail=f"The model could not complete this rewrite: {exc}"
        ) from exc

    return _to_response(outcome)


class SectionText(BaseModel):
    id: str
    text: str


class ExportRequest(BaseModel):
    sections: list[SectionText]


@app.post("/documents/{document_id}/export")
async def export_document(document_id: str, request: ExportRequest) -> Response:
    """Build a real .docx of the document as it currently stands, and send it
    back as a file.

    Section order and headings always come from the stored document, never
    from the request — the request can only supply text. A section missing
    from the request keeps its original text; an unrecognized id is ignored.
    """
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(
            status_code=404, detail="No document with that id — upload it again."
        )

    submitted = {s.id: s.text for s in request.sections}
    sections = overlay_texts(document.sections, submitted)

    return Response(
        content=build_docx(sections),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="rewritten-document.docx"'},
    )

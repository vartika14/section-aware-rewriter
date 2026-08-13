"""HTTP surface.

The browser talks to this directly — there is no Next.js proxy layer, so CORS
is enabled for the dev front end.
"""

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import store
from .parsing import Section, UnparseableDocument, parse_docx

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

"""Tests for the HTTP surface.

Only the upload endpoint exists so far. It is the contract the front end is
built against, so the shape of the response is worth pinning down.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests.test_parsing import make_docx

client = TestClient(app)

PROPOSAL = [
    ("Heading 1", "1. Executive Summary"),
    ("Normal", "A recommendation the leadership team can act on this quarter."),
    ("Heading 1", "2. Scope of Work"),
    ("Normal", "The engagement is advisory; implementation is out of scope."),
    ("Heading 1", "3. Fees"),
    ("Normal", "A fixed fee of EUR 48,000 covers the scope set out in section 2."),
]


def upload(data: bytes, filename: str = "proposal.docx"):
    return client.post(
        "/documents",
        files={
            "file": (
                filename,
                data,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )


def test_upload_returns_a_document_id_and_its_sections():
    response = upload(make_docx(PROPOSAL))

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"]
    assert [s["heading"] for s in body["sections"]] == [
        "1. Executive Summary",
        "2. Scope of Work",
        "3. Fees",
    ]
    assert [s["id"] for s in body["sections"]] == ["s1", "s2", "s3"]
    assert body["headings_detected"] is True


def test_upload_rejects_a_file_that_is_not_a_docx():
    response = upload(b"definitely not a docx", filename="notes.docx")

    assert response.status_code == 400
    assert "docx" in response.json()["detail"].lower()


def test_upload_rejects_a_non_docx_extension():
    response = upload(make_docx(PROPOSAL), filename="proposal.pdf")

    assert response.status_code == 400

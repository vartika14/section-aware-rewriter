"""Tests for the HTTP surface.

Only the upload endpoint exists so far. It is the contract the front end is
built against, so the shape of the response is worth pinning down.
"""

import pytest
from fastapi.testclient import TestClient

from app.llm import ModelRefusal
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


# --- rewrite -------------------------------------------------------------


@pytest.fixture
def document_id() -> str:
    return upload(make_docx(PROPOSAL)).json()["document_id"]


@pytest.fixture
def fake_model(monkeypatch):
    """Substitute the one seam every model call passes through."""

    def fake_completion(*, system, user, schema):
        return schema(new_text="Concrete deliverables: a current-state map.")

    monkeypatch.setattr("app.agent.structured_completion", fake_completion)


def test_rewrite_returns_the_new_text_alongside_the_old(document_id, fake_model):
    response = client.post(
        "/rewrite",
        json={
            "document_id": document_id,
            "section_id": "s2",
            "instruction": "Make this concrete. Name the deliverables.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == "Concrete deliverables: a current-state map."
    assert body["old_text"] == PROPOSAL[3][1]
    assert body["section_id"] == "s2"


def test_rewrite_404s_on_an_unknown_document(fake_model):
    response = client.post(
        "/rewrite",
        json={"document_id": "nope", "section_id": "s1", "instruction": "Be concrete."},
    )

    assert response.status_code == 404
    # Asserted on the message too: a missing *route* also 404s, so the status
    # code alone would pass before the endpoint existed.
    assert "document" in response.json()["detail"].lower()


def test_rewrite_404s_on_an_unknown_section(document_id, fake_model):
    response = client.post(
        "/rewrite",
        json={
            "document_id": document_id,
            "section_id": "s99",
            "instruction": "Be concrete.",
        },
    )

    assert response.status_code == 404
    assert "section" in response.json()["detail"].lower()


def test_rewrite_surfaces_a_model_failure_rather_than_a_500(document_id, monkeypatch):
    """A refusal or a garbled response is an expected operating condition, not a
    crash. The user needs to be told the model failed, not shown a stack trace."""

    def refuse(*, system, user, schema):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.agent.structured_completion", refuse)

    response = client.post(
        "/rewrite",
        json={
            "document_id": document_id,
            "section_id": "s2",
            "instruction": "Be concrete.",
        },
    )

    assert response.status_code == 502
    assert "model" in response.json()["detail"].lower()


def test_rewrite_rejects_a_blank_instruction(document_id, fake_model):
    response = client.post(
        "/rewrite",
        json={"document_id": document_id, "section_id": "s2", "instruction": "   "},
    )

    assert response.status_code == 422

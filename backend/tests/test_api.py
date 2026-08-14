"""Tests for the HTTP surface.

Only the upload endpoint exists so far. It is the contract the front end is
built against, so the shape of the response is worth pinning down.
"""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.audit import AuditResult, Finding
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


NEW_TEXT = "Concrete deliverables: a current-state map."


@pytest.fixture
def fake_model(monkeypatch):
    """Substitute every seam the pipeline calls, and hand the test the audit.

    The rewrite is three model calls now — draft, audit, and the phrasing of any
    question. Mutate `audit["result"]` to script what the audit finds; the
    default is a clean bill of health.

    The phrasing call is made to fail on purpose so these tests assert on the
    deterministic question. What the endpoint returns is this file's business;
    how the sentence reads is `test_question.py`'s.
    """
    audit = {"result": AuditResult(instruction_applicable=True, findings=[])}

    monkeypatch.setattr(
        "app.agent.structured_completion",
        lambda **kwargs: kwargs["schema"](new_text=NEW_TEXT),
    )
    monkeypatch.setattr("app.audit.structured_completion", lambda **kw: audit["result"])
    monkeypatch.setattr(
        "app.question.structured_completion",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("phrasing offline")),
    )
    return audit


def blocking_finding(**overrides) -> Finding:
    """Verified, unresolvable — the fee's premise no longer holds."""
    return Finding(
        **{
            "section_id": "s3",
            "quote": "A fixed fee of EUR 48,000",
            "kind": "invalidated_premise",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "resolvable_from_document": False,
            **overrides,
        }
    )


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

    def refuse(*, system, user, schema, **kwargs):
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


# --- the clarification loop ----------------------------------------------


def rewrite(document_id: str, section_id: str = "s2", instruction: str = "Be concrete."):
    return client.post(
        "/rewrite",
        json={
            "document_id": document_id,
            "section_id": section_id,
            "instruction": instruction,
        },
    )


def test_a_clean_rewrite_completes_with_no_ripples(document_id, fake_model):
    body = rewrite(document_id).json()

    assert body["status"] == "complete"
    assert body["ripples"] == []


def test_a_blocking_finding_suspends_and_asks(document_id, fake_model):
    fake_model["result"] = AuditResult(
        instruction_applicable=True, findings=[blocking_finding()]
    )

    body = rewrite(document_id).json()

    assert body["status"] == "needs_clarification"
    assert body["session_id"]
    assert "A fixed fee of EUR 48,000" in body["question"]
    assert [option["key"] for option in body["options"]] == ["a", "b", "c"]


def test_the_suspended_run_is_kept_so_it_can_be_resumed(document_id, fake_model):
    """The session is the whole point of suspending. Without it the answer has
    nothing to resume into."""
    fake_model["result"] = AuditResult(
        instruction_applicable=True, findings=[blocking_finding()]
    )

    session_id = rewrite(document_id, instruction="Name the deliverables.").json()[
        "session_id"
    ]

    session = store.get_session(session_id)
    assert session is not None
    assert session.instruction == "Name the deliverables."
    assert session.draft_text == NEW_TEXT
    assert session.groups[0].section_id == "s3"


def test_a_non_blocking_finding_completes_but_is_reported(document_id, fake_model):
    """The consultant is told the summary drifted; they are not asked about it."""
    fake_model["result"] = AuditResult(
        instruction_applicable=True,
        findings=[
            blocking_finding(
                section_id="s1",
                quote="act on this quarter",
                kind="stale_reference",
                explanation="The summary still describes the older, vaguer scope.",
            )
        ],
    )

    body = rewrite(document_id).json()

    assert body["status"] == "complete"
    assert body["ripples"][0]["heading"] == "1. Executive Summary"
    assert body["ripples"][0]["verified"] is True


def test_an_ungrounded_finding_never_becomes_a_question(document_id, fake_model):
    """The model claims a conflict whose quote is nowhere in the document.
    Reported, flagged, but not worth interrupting anyone over."""
    fake_model["result"] = AuditResult(
        instruction_applicable=True,
        findings=[blocking_finding(quote="a fixed fee of EUR 90,000")],
    )

    body = rewrite(document_id).json()

    assert body["status"] == "complete"
    assert body["ripples"][0]["verified"] is False


def test_an_instruction_that_makes_no_sense_is_declined(document_id, fake_model):
    fake_model["result"] = AuditResult(
        instruction_applicable=False,
        inapplicable_reason="That section sets no deadline to bring forward.",
    )

    body = rewrite(document_id, instruction="Bring the deadline forward.").json()

    assert body["status"] == "declined"
    assert "deadline" in body["reason"]

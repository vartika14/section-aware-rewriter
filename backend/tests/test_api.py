"""Tests for the HTTP surface.

Only the upload endpoint exists so far. It is the contract the front end is
built against, so the shape of the response is worth pinning down.
"""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.conflicts import Conflict
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
    """Substitute DRAFT and DETECT. Mutate `state["conflicts"]` to script what
    DETECT finds; default is a clean bill of health. There's no phrasing call
    to fake any more — the question is built from Python alone."""
    state = {"conflicts": []}

    monkeypatch.setattr(
        "app.rewrite.structured_completion",
        lambda **kw: kw["schema"](applicable=True, new_text=NEW_TEXT),
    )
    monkeypatch.setattr(
        "app.conflicts.structured_completion",
        lambda **kw: kw["schema"](findings=[c.model_dump() for c in state["conflicts"]]),
    )
    return state


def blocking_conflict(**overrides) -> Conflict:
    return Conflict(
        **{
            "section_id": "s3", "quote": "A fixed fee of EUR 48,000",
            "explanation": "The fee was priced against the old, vaguer scope.",
            "blocking": True, **overrides,
        }
    )


def rewrite(
    document_id: str, section_id: str = "s2", instruction: str = "Be concrete.",
    current_texts: dict | None = None,
):
    body = {"document_id": document_id, "section_id": section_id, "instruction": instruction}
    if current_texts is not None:
        body["current_texts"] = current_texts
    return client.post("/rewrite", json=body)


def test_rewrite_returns_the_new_text_alongside_the_old(document_id, fake_model):
    response = rewrite(document_id, instruction="Make this concrete. Name the deliverables.")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == NEW_TEXT
    assert body["old_text"] == PROPOSAL[3][1]
    assert body["section_id"] == "s2"


def test_rewrite_404s_on_an_unknown_document(fake_model):
    response = rewrite("nope", section_id="s1")
    assert response.status_code == 404
    # Asserted on the message too: a missing *route* also 404s, so the status
    # code alone would pass before the endpoint existed.
    assert "document" in response.json()["detail"].lower()


def test_rewrite_404s_on_an_unknown_section(document_id, fake_model):
    response = rewrite(document_id, section_id="s99")
    assert response.status_code == 404
    assert "section" in response.json()["detail"].lower()


def test_rewrite_surfaces_a_model_failure_rather_than_a_500(document_id, monkeypatch):
    """A refusal or a garbled response is an expected operating condition, not a
    crash. The user needs to be told the model failed, not shown a stack trace."""

    def refuse(*, system, user, schema, **kwargs):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.rewrite.structured_completion", refuse)

    response = rewrite(document_id)

    assert response.status_code == 502
    assert "model" in response.json()["detail"].lower()


def test_rewrite_rejects_a_blank_instruction(document_id, fake_model):
    response = client.post(
        "/rewrite",
        json={"document_id": document_id, "section_id": "s2", "instruction": "   "},
    )

    assert response.status_code == 422


# --- the clarification loop ----------------------------------------------


def test_a_clean_rewrite_completes_with_no_notes(document_id, fake_model):
    body = rewrite(document_id).json()
    assert body["status"] == "complete"
    assert body["notes"] == []


def test_a_blocking_finding_suspends_and_asks(document_id, fake_model):
    fake_model["conflicts"] = [blocking_conflict()]

    body = rewrite(document_id).json()

    assert body["status"] == "needs_clarification"
    assert body["session_id"]
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["section_id"] == "s3"
    assert "A fixed fee of EUR 48,000" in group["conflicts"][0]["quote"]
    assert [option["key"] for option in group["options"]] == ["a", "b", "c"]


def test_two_blocking_sections_both_become_rows_in_one_question(document_id, fake_model):
    fake_model["conflicts"] = [
        blocking_conflict(),
        blocking_conflict(section_id="s1", quote="act on this quarter"),
    ]

    body = rewrite(document_id).json()

    assert body["status"] == "needs_clarification"
    assert {g["section_id"] for g in body["groups"]} == {"s3", "s1"}


def test_the_suspended_run_is_kept_so_it_can_be_resumed(document_id, fake_model):
    """The session is the whole point of suspending. Without it the answer has
    nothing to resume into."""
    fake_model["conflicts"] = [blocking_conflict()]

    session_id = rewrite(document_id, instruction="Name the deliverables.").json()[
        "session_id"
    ]

    session = store.get_session(session_id)
    assert session is not None
    assert session.instruction == "Name the deliverables."
    assert session.draft_text == NEW_TEXT
    assert session.asking[0].section_id == "s3"


def test_a_non_blocking_finding_completes_but_is_reported(document_id, fake_model):
    """The consultant is told the summary drifted; they are not asked about it."""
    fake_model["conflicts"] = [
        blocking_conflict(
            section_id="s1", quote="act on this quarter", blocking=False,
            explanation="The summary still describes the older, vaguer scope.",
        )
    ]

    body = rewrite(document_id).json()

    assert body["status"] == "complete"
    assert body["notes"][0]["heading"] == "1. Executive Summary"
    assert body["notes"][0]["verified"] is True


def test_an_ungrounded_finding_never_becomes_a_question(document_id, fake_model):
    """The model claims a conflict whose quote is nowhere in the document.
    Reported, flagged, but not worth interrupting anyone over."""
    fake_model["conflicts"] = [blocking_conflict(quote="a fixed fee of EUR 90,000")]

    body = rewrite(document_id).json()

    assert body["status"] == "complete"
    assert body["notes"][0]["verified"] is False


def test_an_instruction_that_makes_no_sense_is_declined(document_id, monkeypatch):
    monkeypatch.setattr(
        "app.rewrite.structured_completion",
        lambda **kw: kw["schema"](
            applicable=False,
            inapplicable_reason="That section sets no deadline to bring forward.",
        ),
    )

    body = rewrite(document_id, instruction="Bring the deadline forward.").json()

    assert body["status"] == "declined"
    assert "deadline" in body["reason"]


# --- answering the question ----------------------------------------------


def answer(session_id: str, option_key: str = "c", *, section_id: str = "s3"):
    return client.post(
        f"/rewrite/{session_id}/answer", json={"choices": {section_id: option_key}}
    )


@pytest.fixture
def asked(document_id, fake_model):
    fake_model["conflicts"] = [blocking_conflict()]
    body = rewrite(document_id).json()
    assert body["status"] == "needs_clarification"
    return body


def test_answering_completes_the_rewrite(asked):
    response = answer(asked["session_id"], "c")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["new_text"] == NEW_TEXT


def test_answering_never_produces_a_second_question(asked, fake_model):
    """resume()'s return type has no Asking arm — this exercises that at the
    HTTP boundary, where a bug would otherwise be a silently-ignored field."""
    fake_model["conflicts"] = [
        blocking_conflict(section_id="s1", quote="act on this quarter")
    ]
    body = answer(asked["session_id"], "a").json()
    assert body["status"] == "complete"


def test_flagging_keeps_the_finding_as_a_note(asked):
    body = answer(asked["session_id"], "b").json()
    assert [n["section_id"] for n in body["notes"]] == ["s3"]


def test_answering_an_unknown_session_404s(fake_model):
    response = answer("nope")
    assert response.status_code == 404
    assert "session" in response.json()["detail"].lower()


def test_answering_twice_409s(asked):
    answer(asked["session_id"], "c")
    response = answer(asked["session_id"], "c")
    assert response.status_code == 409
    assert "finished" in response.json()["detail"].lower()


def test_an_unrecognised_option_is_a_422(asked):
    assert answer(asked["session_id"], "z").status_code == 422


def test_answering_with_a_missing_section_is_a_422(asked):
    response = client.post(
        f"/rewrite/{asked['session_id']}/answer", json={"choices": {}}
    )
    assert response.status_code == 422


def test_a_lost_document_is_a_404_not_a_500(asked, monkeypatch):
    """State is in memory. A restart between question and answer is real."""
    monkeypatch.setattr("app.store._DOCUMENTS", {})

    response = answer(asked["session_id"], "c")

    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()


def test_a_model_failure_on_a_redraft_is_a_502(asked, monkeypatch):
    def refuse(*, system, user, schema, **kwargs):
        raise ModelRefusal("content filter triggered")

    monkeypatch.setattr("app.rewrite.structured_completion", refuse)

    response = answer(asked["session_id"], "a")

    assert response.status_code == 502
    assert "model" in response.json()["detail"].lower()


# --- downloading the finished document -------------------------------------


def export(document_id: str, sections: list[dict]):
    return client.post(f"/documents/{document_id}/export", json={"sections": sections})


def test_export_includes_the_text_you_sent(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    reread = parse_docx(response.content)
    scope = next(s for s in reread.sections if s.heading == "2. Scope of Work")
    assert scope.text == "A new, concrete scope."


def test_export_keeps_the_original_text_for_a_section_you_did_not_send(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [{"id": "s2", "text": "A new, concrete scope."}])

    reread = parse_docx(response.content)
    fees = next(s for s in reread.sections if s.heading == "3. Fees")
    assert fees.text == PROPOSAL[5][1]


def test_export_ignores_a_section_id_that_does_not_exist(document_id):
    response = export(document_id, [{"id": "s99", "text": "orphaned"}])

    assert response.status_code == 200


def test_export_keeps_the_original_section_order(document_id):
    from app.parsing import parse_docx

    response = export(document_id, [])

    reread = parse_docx(response.content)
    assert [s.heading for s in reread.sections] == [
        "1. Executive Summary", "2. Scope of Work", "3. Fees",
    ]


def test_export_returns_a_clear_error_for_an_unknown_document():
    response = export("nope", [])

    assert response.status_code == 404
    assert "document" in response.json()["detail"].lower()


# --- accepted edits reach a new rewrite -------------------------------------


def test_current_texts_reach_the_rewrite_prompt(document_id, monkeypatch):
    captured = {}

    def draft(**kwargs):
        captured["user"] = kwargs["user"]
        return kwargs["schema"](applicable=True, new_text=NEW_TEXT)

    monkeypatch.setattr("app.rewrite.structured_completion", draft)
    monkeypatch.setattr(
        "app.conflicts.structured_completion", lambda **kw: kw["schema"](findings=[])
    )

    rewrite(
        document_id, section_id="s2",
        current_texts={"s3": "A renegotiated fee of EUR 90,000."},
    )

    assert "A renegotiated fee of EUR 90,000." in captured["user"]


def test_a_rewrite_request_without_current_texts_still_works(document_id, fake_model):
    response = rewrite(document_id)

    assert response.status_code == 200

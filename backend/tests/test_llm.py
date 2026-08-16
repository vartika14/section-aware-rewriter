"""Tests for the one seam every model call passes through.

The OpenAI client is substituted rather than the seam itself — these are the
tests of the seam, so substituting it would leave nothing under test.
"""

import pytest
from pydantic import BaseModel

from app import llm
from app.llm import ModelRefusal, structured_completion


class Answer(BaseModel):
    text: str


class FakeMessage:
    def __init__(self, parsed=None, refusal=None):
        self.parsed = parsed
        self.refusal = refusal


class FakeClient:
    """Records calls and replays a scripted sequence of messages."""

    def __init__(self, *messages):
        self.messages = list(messages)
        self.calls: list[dict] = []
        self.chat = self

    @property
    def completions(self):
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        message = self.messages.pop(0)
        return type("Response", (), {"choices": [type("C", (), {"message": message})]})


@pytest.fixture
def fake_client(monkeypatch):
    def install(*messages):
        client = FakeClient(*messages)
        monkeypatch.setattr(llm, "_client", lambda: client)
        return client

    return install


def test_a_parsed_response_comes_back_as_the_schema(fake_client):
    fake_client(FakeMessage(parsed=Answer(text="ok")))

    assert structured_completion(system="s", user="u", schema=Answer).text == "ok"


def test_temperature_is_passed_through_when_given(fake_client):
    """The audit call pins this to 0. If it were silently dropped, the interrupt
    policy would fire intermittently and no test here would notice."""
    client = fake_client(FakeMessage(parsed=Answer(text="ok")))

    structured_completion(system="s", user="u", schema=Answer, temperature=0)

    assert client.calls[0]["temperature"] == 0


def test_temperature_is_omitted_when_not_given(fake_client):
    """Not every deployment accepts an explicit temperature; the draft call has
    no need of one."""
    client = fake_client(FakeMessage(parsed=Answer(text="ok")))

    structured_completion(system="s", user="u", schema=Answer)

    assert "temperature" not in client.calls[0]


def test_an_unparseable_response_is_retried_once(fake_client):
    """A schema violation is usually a one-off. Retrying once costs a second and
    saves the user an error they can do nothing about."""
    client = fake_client(
        FakeMessage(parsed=None, refusal=None), FakeMessage(parsed=Answer(text="ok"))
    )

    result = structured_completion(system="s", user="u", schema=Answer)

    assert result.text == "ok"
    assert len(client.calls) == 2


def test_a_second_failure_raises_rather_than_returning_something_partial(fake_client):
    client = fake_client(FakeMessage(parsed=None), FakeMessage(parsed=None))

    with pytest.raises(ModelRefusal):
        structured_completion(system="s", user="u", schema=Answer)

    assert len(client.calls) == 2


def test_an_outright_refusal_is_not_retried(fake_client):
    """A content filter will refuse again. Retrying just doubles the latency
    before the user is told."""
    client = fake_client(FakeMessage(parsed=None, refusal="content filter"))

    with pytest.raises(ModelRefusal, match="content filter"):
        structured_completion(system="s", user="u", schema=Answer)

    assert len(client.calls) == 1


def test_a_pinned_retry_is_nudged_off_zero(fake_client):
    """A retry that repeats the request byte for byte mostly repeats the answer.

    Both graded calls pin temperature to 0, so a deterministic schema failure
    would have failed twice and called it a retry. The second attempt is nudged
    just far enough to break that, and no further: one retry, then stop.
    """
    client = fake_client(
        FakeMessage(parsed=None, refusal=None), FakeMessage(parsed=Answer(text="ok"))
    )

    structured_completion(system="s", user="u", schema=Answer, temperature=0)

    assert client.calls[0]["temperature"] == 0
    assert client.calls[1]["temperature"] > 0


def test_an_unpinned_retry_stays_unpinned(fake_client):
    """Nothing is invented for a caller that never asked for a temperature."""
    client = fake_client(
        FakeMessage(parsed=None, refusal=None), FakeMessage(parsed=Answer(text="ok"))
    )

    structured_completion(system="s", user="u", schema=Answer)

    assert "temperature" not in client.calls[1]

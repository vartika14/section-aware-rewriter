"""Tests for reading credentials out of the environment.

API keys are stored base64-encoded in .env and decoded on load — not
encryption, just enough that a raw key isn't sitting in plain text in a file
someone might glance at or `cat`. A key that fails to decode is a configuration
error the app should refuse to start with, not something it silently ignores.
"""

import base64

import pytest
from pydantic import ValidationError

from app.config import Settings


def encoded(raw: str) -> str:
    return base64.b64encode(raw.encode()).decode()


def test_a_base64_encoded_key_decodes_to_the_raw_value(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", encoded("sk-real-key"))
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-real-key"


def test_both_azure_and_openai_keys_are_decoded(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", encoded("azure-secret"))
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", encoded("openai-secret"))

    settings = Settings(_env_file=None)

    assert settings.azure_openai_api_key == "azure-secret"
    assert settings.openai_api_key == "openai-secret"


def test_an_unset_key_is_left_as_none(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.azure_openai_api_key is None
    assert settings.openai_api_key is None


def test_a_raw_unencoded_key_is_rejected_rather_than_sent_to_the_model(monkeypatch):
    """A plaintext key pasted in by mistake must fail loudly at startup, not
    reach Azure as a garbled, mis-decoded string and produce a confusing auth
    error three layers away from the actual mistake."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-base64-at-all!!")

    with pytest.raises(ValidationError, match="base64"):
        Settings(_env_file=None)

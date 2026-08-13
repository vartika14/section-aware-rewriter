"""Environment configuration.

Credentials live in `backend/.env`, which is gitignored. Copy `.env.example`
and fill it in.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

Provider = Literal["azure", "openai"]


class MissingCredentials(RuntimeError):
    """Raised when no usable LLM credentials are configured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure OpenAI — what Sherpa supplies with the brief.
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    # Plain OpenAI — a fallback so the build isn't blocked waiting on the Azure key.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-2024-08-06"

    @property
    def provider(self) -> Provider:
        """Which provider to use. Azure wins when both are configured."""
        if self.azure_openai_api_key and self.azure_openai_endpoint and self.azure_openai_deployment:
            return "azure"
        if self.openai_api_key:
            return "openai"
        raise MissingCredentials(
            "No LLM credentials found. Copy backend/.env.example to backend/.env "
            "and fill in either the Azure block (endpoint + key + deployment) "
            "or OPENAI_API_KEY."
        )

    @property
    def model(self) -> str:
        """The deployment name on Azure, or the model name on OpenAI."""
        if self.provider == "azure":
            assert self.azure_openai_deployment  # narrowed by provider check
            return self.azure_openai_deployment
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    return Settings()

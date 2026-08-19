"""The one function every AI call in this app goes through.

Keeping it to one function means the Azure-vs-OpenAI difference lives in one
place, and tests have exactly one thing to fake.
"""

from functools import lru_cache
from typing import TypeVar

from openai import AzureOpenAI, OpenAI
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


class ModelRefusal(RuntimeError):
    """The model declined to answer, or returned nothing parseable."""


@lru_cache
def _client() -> AzureOpenAI | OpenAI:
    settings = get_settings()
    if settings.provider == "azure":
        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    return OpenAI(api_key=settings.openai_api_key)


def structured_completion(
    *, system: str, user: str, schema: type[T], temperature: float | None = None
) -> T:
    """Call the model and return a validated instance of `schema`.

    Uses structured outputs, so the model's response is constrained to match
    the schema instead of just being asked nicely for JSON.

    `temperature` is optional — DRAFT and DETECT pin it to 0, so the same
    input gives the same decision. Other calls use the deployment's default.

    A response that fails to parse is retried once, with the temperature
    nudged up slightly (so a deterministic failure doesn't just fail the
    same way twice). An outright refusal is never retried — a content filter
    will refuse again, and retrying only delays telling the user.
    """
    settings = get_settings()

    for attempt in range(2):
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = (
                temperature if attempt == 0 else min(temperature + 0.2, 1.0)
            )

        message = (
            _client()
            .chat.completions.parse(
                model=settings.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                **kwargs,
            )
            .choices[0]
            .message
        )

        if message.parsed is not None:
            return message.parsed
        if message.refusal:
            raise ModelRefusal(message.refusal)

    raise ModelRefusal("Model returned no parseable content, twice.")

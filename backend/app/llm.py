"""The single seam through which every model call passes.

There is one function here on purpose. It means the Azure-vs-OpenAI difference is
confined to this file, and the agent has exactly one place to substitute in tests.
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


def structured_completion(*, system: str, user: str, schema: type[T]) -> T:
    """Call the model and return a validated instance of `schema`.

    Uses structured outputs, so the model is constrained to the schema rather
    than asked politely to emit JSON.
    """
    settings = get_settings()
    response = _client().chat.completions.parse(
        model=settings.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=schema,
    )

    message = response.choices[0].message
    if message.parsed is None:
        raise ModelRefusal(message.refusal or "Model returned no parseable content.")
    return message.parsed

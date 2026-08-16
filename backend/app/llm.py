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


def structured_completion(
    *, system: str, user: str, schema: type[T], temperature: float | None = None
) -> T:
    """Call the model and return a validated instance of `schema`.

    Uses structured outputs, so the model is constrained to the schema rather
    than asked politely to emit JSON.

    `temperature` is optional rather than defaulted because only one caller needs
    it: the audit, which pins it to 0 so the interrupt policy cannot fire
    intermittently. Everything else takes the deployment's default.

    A response that fails to parse is retried once — schema violations are
    usually a one-off, and a silent partial result is never returned. An outright
    refusal is not retried: a content filter will refuse again, and retrying only
    delays telling the user.

    The retry is nudged off a pinned temperature. Repeating a request byte for
    byte mostly repeats the answer, and both graded calls sit at 0 — so without
    the nudge a deterministic schema failure would fail twice and call itself a
    retry. The nudge is small and applies only to the second attempt, so the
    determinism the pinning buys is intact for every call that succeeds.
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

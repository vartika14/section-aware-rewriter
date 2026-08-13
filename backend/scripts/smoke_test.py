"""Phase 0: prove the model call works before building anything on top of it.

Run:  python -m scripts.smoke_test      (from backend/, with the venv active)

This is a connectivity check, not a unit test. It answers three questions that
would otherwise surface much later and much more expensively:

  1. Do the credentials work at all?
  2. Does this deployment support structured outputs?
  3. Does a Pydantic model come back populated?
"""

import sys

from pydantic import BaseModel

from app.config import MissingCredentials, get_settings
from app.llm import ModelRefusal, structured_completion


class SmokeResult(BaseModel):
    """Deliberately shaped like the real audit schema: a literal-ish field, a
    bool, and an optional string. If this round-trips, the real one will too."""

    city: str
    country: str
    is_capital: bool
    founded_year: int | None = None


def main() -> int:
    try:
        settings = get_settings()
        provider = settings.provider
    except MissingCredentials as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    print(f"provider : {provider}")
    print(f"model    : {settings.model}")
    print("calling  : ...", flush=True)

    try:
        result = structured_completion(
            system="You extract structured facts. Answer only from general knowledge.",
            user="Amsterdam.",
            schema=SmokeResult,
        )
    except ModelRefusal as exc:
        print(f"✗ model refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — this is a diagnostic script
        print(f"✗ call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"✓ parsed : {result!r}")
    print("\nPhase 0 exit criterion met: a populated Pydantic object from a real call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

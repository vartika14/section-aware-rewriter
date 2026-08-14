"""Comparing text the way a reader would.

Used for matching quotes and headings against the document. Lives on its own
because both the audit boundary and the policy need it, and the audit cannot
import the policy — the policy is built on top of it.
"""

import re


def normalize(text: str) -> str:
    """Compare on words, not formatting.

    Reflowed whitespace and changed case are ordinary things for a model to do
    when copying text. Only invented words should read as invented.
    """
    return re.sub(r"\s+", " ", text).strip().lower()

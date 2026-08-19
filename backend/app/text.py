"""Comparing text the way a reader would, ignoring whitespace and case.

Used wherever a quote from the model needs to be checked against the real
document text.
"""

import re


def normalize(text: str) -> str:
    """Strip formatting differences so only real word changes show up as
    different. A model reflowing whitespace or changing case while copying a
    quote shouldn't count as inventing something."""
    return re.sub(r"\s+", " ", text).strip().lower()

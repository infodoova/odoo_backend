"""
Model-specific request parameters for the Claude 5 family.

Thinking cannot be switched off the same way on every model, and some models that are sent no
``thinking`` setting at all think on their own, spending the output budget before they write
the answer (so short calls come back cut off or empty). Verified against the API:

    model                      "disabled"   "between_tools"   "adaptive"
    claude-haiku-5-5           accepted     rejected          accepted
    claude-sonnet-5-5          rejected     accepted          accepted
    claude-opus-5-5            rejected     rejected          accepted (cannot be turned off)
    claude-sonnet-5            accepted     rejected          accepted
    claude-haiku-4-5-20251001  accepted     -                 rejected (no adaptive thinking)

The rules are by exact model family, not by the word "sonnet" or "haiku" in the name:
claude-sonnet-5 and claude-sonnet-5-5 need different values.
``thinking_param`` returns the right value for the model, so no caller has to know this.
"""

from __future__ import annotations

import re
from typing import Optional

# Claude 3.x and 4.x: no adaptive thinking; they do not think unless asked to.
_LEGACY = re.compile(r"^claude-(?:3|(?:opus|sonnet|haiku)-4)(?:\b|[-.])")


def thinking_param(model: Optional[str], enabled: bool) -> Optional[dict]:
    """The ``thinking`` request parameter for ``model``, or ``None`` to send none.

    ``enabled=True`` asks for adaptive thinking (older models get nothing: they cannot do
    adaptive thinking). ``enabled=False`` asks for the model's own way of not thinking before
    it answers (opus 5 has none: it keeps adaptive thinking).
    """
    name = (model or "").strip().lower()
    is_claude = name.startswith("claude")
    legacy = bool(_LEGACY.match(name))

    if enabled:
        return None if legacy else {"type": "adaptive"}

    if not is_claude:
        return None  # unknown model: send nothing rather than a value it may reject
    if name.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}
    if name.startswith("claude-opus-5"):
        return {"type": "adaptive"}
    return {"type": "disabled"}  # haiku-5-5, sonnet-5, and Claude 3.x / 4.x


def thinking_kwargs(model: Optional[str], enabled: bool = False) -> dict:
    """``{"thinking": ...}`` ready to splat into a request, or ``{}``."""
    value = thinking_param(model, enabled)
    return {"thinking": value} if value else {}

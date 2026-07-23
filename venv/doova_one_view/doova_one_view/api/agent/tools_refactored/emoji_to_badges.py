import re

# Ordered so multi-character / more specific patterns are checked first.
# Each entry: (emoji_or_pattern, badge_class, badge_label)
_EMOJI_MAP = [
    ("ðŸš¨", "badge-urgent", "URGENT"),
    ("ðŸ”´", "badge-critical", "CRITICAL"),
    ("ðŸŸ ", "badge-high", "HIGH"),
    ("ðŸŸ¡", "badge-medium", "MEDIUM"),
    ("ðŸŸ¢", "badge-good", "GOOD"),
    ("âš ï¸", "badge-warning", "WARNING"),
    ("âš ", "badge-warning", "WARNING"),
    ("âœ…", "badge-good", "OK"),
    ("âŒ", "badge-critical", "FAILED"),
]

# Matches an emoji immediately followed by an explicit label word, so we can
# keep the AI's own word (e.g. "ðŸ”´ URGENT" -> keep "URGENT") instead of
# forcing the generic default label above (e.g. "ðŸ”´ HIGH" -> "HIGH", not
# "CRITICAL"). Falls back to the default label if no word follows.
_LABEL_AFTER = re.compile(
    r"(" + "|".join(re.escape(e) for e, _, _ in _EMOJI_MAP) + r")\s*"
    r"([A-Za-z][A-Za-z\s]{0,20}?)(?=[\s.,:!<]|$)"
)

_CLASS_BY_EMOJI = {e: cls for e, cls, _ in _EMOJI_MAP}
_DEFAULT_LABEL_BY_EMOJI = {e: label for e, cls, label in _EMOJI_MAP}

# Cleans up already-bracketed fallback text from older/existing content,
# e.g. "[Alert] Critical" or "[CRITICAL]" on its own, so it also gets
# upgraded to a real badge instead of being left as literal brackets.
_BRACKET_TAG = re.compile(r"\[(Alert|Note|Good|Watch|Warning|Critical|Urgent)\]\s*([A-Za-z][A-Za-z\s]{0,20})?", re.IGNORECASE)

_BRACKET_CLASS = {
    "alert": "badge-critical",
    "critical": "badge-critical",
    "urgent": "badge-urgent",
    "warning": "badge-warning",
    "watch": "badge-medium",
    "note": "badge-note",
    "good": "badge-good",
}


def _emoji_replacer(match: "re.Match") -> str:
    emoji = match.group(1)
    trailing_word = (match.group(2) or "").strip()
    label = trailing_word if trailing_word else _DEFAULT_LABEL_BY_EMOJI[emoji]
    cls = _CLASS_BY_EMOJI[emoji]
    return f'<span class="badge {cls}">{label.upper()}</span>'


def _bracket_replacer(match: "re.Match") -> str:
    tag = match.group(1).lower()
    trailing_word = (match.group(2) or "").strip()
    label = trailing_word if trailing_word else tag
    cls = _BRACKET_CLASS.get(tag, "badge-note")
    return f'<span class="badge {cls}">{label.upper()}</span>'


def normalize_status_emoji(text: str) -> str:
    """
    Replace status emoji (and any already-bracketed fallback text like
    '[Alert]') with styled <span class="badge ...">LABEL</span> tags.

    Safe to run on raw markdown OR on already-converted HTML â€” it only
    touches the emoji/bracket characters themselves, not surrounding markup.
    """
    if not text:
        return text
    text = _LABEL_AFTER.sub(_emoji_replacer, text)
    text = _BRACKET_TAG.sub(_bracket_replacer, text)
    # Catch any remaining standalone emoji not followed by a label word
    for emoji, cls, label in _EMOJI_MAP:
        text = text.replace(emoji, f'<span class="badge {cls}">{label}</span>')
    return text



"""
doova_one_view/api/agent/tools_refactored/emoji_to_badges.py

Converts emojis, severity tags ([CRITICAL], [WARNING], [HIGH]), markdown prefixes,
and table cell status keywords into styled HTML badges for executive PDF reports.
"""

import re

# 1. Unicode Emojis mapped to (class, default_label)
_EMOJI_MAP = [
    ("🚨", "badge-urgent", "URGENT"),
    ("🔴", "badge-critical", "CRITICAL"),
    ("❌", "badge-critical", "FAILED"),
    ("⛔", "badge-critical", "BLOCKED"),
    ("🟠", "badge-high", "HIGH"),
    ("⚠️", "badge-warning", "WARNING"),
    ("⚡", "badge-warning", "ALERT"),
    ("🟡", "badge-medium", "MEDIUM"),
    ("🟢", "badge-good", "HEALTHY"),
    ("✅", "badge-good", "OK"),
    ("ℹ️", "badge-info", "INFO"),
    ("🔹", "badge-info", "NOTE"),
]

# 2. Tag categories for bracketed tokens [CRITICAL], [Warning], etc.
_TAG_CLASS_MAP = {
    "critical": "badge-critical",
    "severe": "badge-critical",
    "danger": "badge-critical",
    "failed": "badge-critical",
    "fail": "badge-critical",
    "breach": "badge-critical",
    "urgent": "badge-urgent",
    "alert": "badge-critical",
    "warning": "badge-warning",
    "warn": "badge-warning",
    "high": "badge-high",
    "medium": "badge-medium",
    "moderate": "badge-medium",
    "low": "badge-info",
    "info": "badge-info",
    "note": "badge-note",
    "good": "badge-good",
    "healthy": "badge-good",
    "ok": "badge-good",
    "passed": "badge-good",
    "pass": "badge-good",
    "action required": "badge-urgent",
    "in progress": "badge-info",
    "monitoring": "badge-warning",
}

_BRACKET_REGEX = re.compile(
    r'\[(Critical|Severe|Danger|Failed|Fail|Breach|Urgent|Alert|Warning|Warn|High|Medium|Moderate|Low|Info|Note|Good|Healthy|OK|Passed|Pass|Action Required|In Progress|Monitoring)\](?:\s*([A-Za-z0-9_\-\s]{1,25}))?',
    re.IGNORECASE
)

_PREFIX_REGEX = re.compile(
    r'\*\*(Critical|Warning|Urgent|Alert|Action Required|Healthy|Failed):\*\*',
    re.IGNORECASE
)

_TABLE_STATUS_REGEX = re.compile(
    r'(\|\s*)(Critical|Severe|Urgent|Warning|High|Medium|Moderate|Low|Healthy|OK|Good|Failed|Action Required)(\s*\|)',
    re.IGNORECASE
)

_ARROW_STATUS_REGEX = re.compile(
    r'(→|->)\s*(Critical|Severe|Urgent|Warning|High|Medium|Moderate|Low|Healthy|OK|Good)\b',
    re.IGNORECASE
)

_STATUS_KEY_REGEX = re.compile(
    r'\b(Status Flag|Overall Status|Status|Severity|Priority):\s*(Critical|Severe|Urgent|Warning|High|Medium|Moderate|Low|Healthy|OK|Good)\b',
    re.IGNORECASE
)

_QUOTED_STATUS_REGEX = re.compile(
    r'"(Critical|Warning|Urgent|High|Medium|Healthy|OK)"\s*status\b',
    re.IGNORECASE
)


def _bracket_replacer(match: re.Match) -> str:
    tag_raw = match.group(1).strip()
    tag_key = tag_raw.lower()
    trailing = (match.group(2) or "").strip()
    cls = _TAG_CLASS_MAP.get(tag_key, "badge-note")
    label = trailing.upper() if trailing else tag_raw.upper()
    return f'<span class="badge {cls}">{label}</span>'


def _prefix_replacer(match: re.Match) -> str:
    tag_raw = match.group(1).strip()
    tag_key = tag_raw.lower()
    cls = _TAG_CLASS_MAP.get(tag_key, "badge-warning")
    return f'<span class="badge {cls}">{tag_raw.upper()}</span>'


def _table_status_replacer(match: re.Match) -> str:
    prefix_pipe = match.group(1)
    status_text = match.group(2).strip()
    suffix_pipe = match.group(3)
    cls = _TAG_CLASS_MAP.get(status_text.lower(), "badge-info")
    return f'{prefix_pipe}<span class="badge {cls}">{status_text.upper()}</span>{suffix_pipe}'


def _arrow_status_replacer(match: re.Match) -> str:
    arrow = match.group(1)
    st = match.group(2).strip()
    cls = _TAG_CLASS_MAP.get(st.lower(), "badge-info")
    return f'{arrow} <span class="badge {cls}">{st.upper()}</span>'


def _status_key_replacer(match: re.Match) -> str:
    key_name = match.group(1)
    st = match.group(2).strip()
    cls = _TAG_CLASS_MAP.get(st.lower(), "badge-info")
    return f'{key_name}: <span class="badge {cls}">{st.upper()}</span>'


def _quoted_status_replacer(match: re.Match) -> str:
    st = match.group(1).strip()
    cls = _TAG_CLASS_MAP.get(st.lower(), "badge-info")
    return f'<span class="badge {cls}">{st.upper()}</span> status'


def normalize_status_emoji(text: str) -> str:
    """
    Transforms emojis, bracket tags, markdown prefixes, table status cells,
    and status indicators into styled executive badges with full color classes.
    """
    if not text:
        return text

    # 1. Replace bracketed tags [CRITICAL], [Warning], etc.
    text = re.sub(r'\*\*\s*\[(.*?)\]\s*\*\*', r'[\1]', text)
    text = _BRACKET_REGEX.sub(_bracket_replacer, text)

    # 2. Replace bold markdown prefixes e.g. **Critical:** -> badge
    text = _PREFIX_REGEX.sub(_prefix_replacer, text)

    # 3. Replace standalone table cells e.g. | Critical | -> badge
    text = _TABLE_STATUS_REGEX.sub(_table_status_replacer, text)

    # 4. Replace arrows and status indicators e.g. "-> Critical" or "Overall Status Flag: Critical"
    text = _ARROW_STATUS_REGEX.sub(_arrow_status_replacer, text)
    text = _STATUS_KEY_REGEX.sub(_status_key_replacer, text)
    text = _QUOTED_STATUS_REGEX.sub(_quoted_status_replacer, text)

    # 5. Replace Unicode Emojis
    for emoji, cls, label in _EMOJI_MAP:
        text = re.sub(
            re.escape(emoji) + r'\s*([A-Za-z0-9_\-\s]{1,20})?(?=[\s.,:!<|]|$)',
            lambda m, c=cls, d=label: f'<span class="badge {c}">{(m.group(1).strip().upper() if m.group(1) else d)}</span>',
            text
        )
        text = text.replace(emoji, f'<span class="badge {cls}">{label}</span>')

    return text

"""
Per-run store for tables that tools build, so the model never retypes rows.

Why: when the model copies a list of records into its answer it drops rows, invents
values and writes placeholders. Instead a tool renders the table itself, stores it
here, and gives the model a short marker (``{{TABLE:T1}}``). After the model has
written its reply, ``expand_table_markers`` swaps each marker for the stored table.

The store is a ContextVar holding a plain dict, so it is private to one agent run and
tools that run on a copy of the context still write into the same dict.
"""

import re
from contextvars import ContextVar, Token
from typing import Optional

_MARKER = re.compile(r"\{\{\s*TABLE:(T\d+)\s*\}\}")
_BLANK_RUNS = re.compile(r"\n{3,}")

_sink: ContextVar[Optional[dict]] = ContextVar("agent_table_sink", default=None)


def start_table_sink() -> Token:
    """Begin collecting tables for one agent run. Pass the result to end_table_sink."""
    return _sink.set({"tables": {}, "next": 1})


def end_table_sink(token: Token) -> None:
    _sink.reset(token)


def sink_is_active() -> bool:
    return _sink.get() is not None


def register_table(markdown: str, always_show: bool = True) -> Optional[str]:
    """Store a rendered table and return its marker, or None when no run is collecting.

    always_show: append the table to the reply if the model forgets to place the marker.
    """
    sink = _sink.get()
    if sink is None:
        return None
    table_id = f"T{sink['next']}"
    sink["next"] += 1
    sink["tables"][table_id] = {"markdown": markdown, "always_show": always_show}
    return "{{TABLE:%s}}" % table_id


def expand_table_markers(text: str, is_voice: bool = False) -> str:
    """Replace markers in the model's reply with the stored tables.

    - Unknown markers are removed.
    - A table with always_show that the model did not place is appended at the end.
    - Voice replies never contain tables: markers are removed and nothing is appended.
    """
    sink = _sink.get()
    tables = (sink or {}).get("tables", {})
    used = set()

    def _swap(match: "re.Match") -> str:
        table_id = match.group(1)
        entry = tables.get(table_id)
        if is_voice or entry is None:
            return ""
        used.add(table_id)
        return "\n\n" + entry["markdown"] + "\n\n"

    result = _MARKER.sub(_swap, text or "")

    if not is_voice:
        leftovers = [
            entry["markdown"]
            for table_id, entry in tables.items()
            if table_id not in used and entry["always_show"]
        ]
        if leftovers:
            result = result.rstrip() + "\n\n" + "\n\n".join(leftovers)

    return _BLANK_RUNS.sub("\n\n", result).strip()

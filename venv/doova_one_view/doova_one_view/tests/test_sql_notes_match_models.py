"""
Guards the hand-written table notes the SQL agent sees (_TABLE_SEMANTIC_NOTES)
against the real Django models, so a renamed or wrong column breaks the build
instead of making the agent write failing SQL.

No database access is needed: only model metadata is inspected.
"""

import re

from django.apps import apps
from django.test import SimpleTestCase

from doova_one_view.api.agent.sql_agent import _TABLE_SEMANTIC_NOTES

# A column the note declares, e.g. "debit_move_line_id (→fact_account_move_lines.id)"
# or "date_id (int→dim_time.date_id)": a name ending in _id, directly followed by "(".
_DECLARED_COLUMN = re.compile(r"\b([a-z][a-z0-9_]*_id)\s*\(")


def _columns_by_table() -> dict:
    tables = {}
    for model in apps.get_models():
        table = model._meta.db_table
        tables[table] = {f.column for f in model._meta.concrete_fields}
    return tables


class SqlNotesMatchModelsTests(SimpleTestCase):
    def test_every_noted_table_exists_as_a_model(self):
        tables = _columns_by_table()
        missing = sorted(t for t in _TABLE_SEMANTIC_NOTES if t not in tables)
        self.assertEqual(missing, [], f"Notes describe tables with no model: {missing}")

    def test_declared_columns_exist_on_their_table(self):
        tables = _columns_by_table()
        problems = []
        for table, note in _TABLE_SEMANTIC_NOTES.items():
            columns = tables.get(table, set())
            for name in sorted(set(_DECLARED_COLUMN.findall(note))):
                if name not in columns:
                    problems.append(f"{table}: note names column '{name}' which the model does not have")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_partial_reconcile_note_uses_move_line_columns(self):
        note = _TABLE_SEMANTIC_NOTES["fact_account_partial_reconciles"]
        self.assertIn("debit_move_line_id", note)
        self.assertIn("credit_move_line_id", note)
        self.assertNotRegex(note, r"\bdebit_move_id\b")
        self.assertNotRegex(note, r"\bcredit_move_id\b")

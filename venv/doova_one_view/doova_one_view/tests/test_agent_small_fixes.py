"""
Regression tests for the small agent fixes in AGENT_FIXES_PLAN.md (Phase 1).

These are static/metadata checks, so they need no database and no network.
"""

import ast
import inspect

from django.test import SimpleTestCase


def _undefined_global_loads(module) -> set:
    """Names read in the module that are never bound anywhere (assigned, imported, defined, or builtin)."""
    import builtins

    tree = ast.parse(inspect.getsource(module))
    bound = set(dir(builtins))
    loaded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return loaded - bound


class AgentSmallFixesTests(SimpleTestCase):
    def test_langchain_agent_has_logger_for_early_stopping_warning(self):
        from doova_one_view.api.agent import langchain_agent

        self.assertNotIn("logger", _undefined_global_loads(langchain_agent))
        self.assertTrue(hasattr(langchain_agent, "logger"))

    def test_generate_report_tool_has_no_undefined_names(self):
        from doova_one_view.api.agent.tools_refactored.reporting import generate_report_tool

        undefined = _undefined_global_loads(generate_report_tool)
        self.assertNotIn("current_year", undefined)

    def test_unused_company_name_helper_is_removed(self):
        from doova_one_view.api.agent.tools_refactored import common

        self.assertFalse(hasattr(common, "resolve_company_name"))

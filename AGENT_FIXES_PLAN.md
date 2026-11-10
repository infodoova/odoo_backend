# Finance Agent Fixes: Implementation Plan

**Status:** In progress on branch `fix/agent-fixes-plan` (nothing committed yet).
**Date:** 2026-11-06 (updated 2026-11-09)

| Phase | State |
|---|---|
| 0. Set up testing | Done |
| 1. Small fixes | Done, 7 new tests |
| 2. Plan fallback | Done, 19 new tests |
| 3. Chat answers | Code and unit tests done (English-only tables). A live replay of the Conatus chat against the real model has not been run yet |
| 4. Excel export | Deferred |

**Test baseline:** 180 tests, 50 errors before any change. The 50 are old tests that call tools with `tenant_id=` where the code now takes `tenant_ids`; they are unrelated to this plan and are not fixed here. After Phases 1 and 2: 206 tests, the same 50 errors, no new failures.

Run tests from `venv/doova_one_view` with `../Scripts/python.exe manage.py test doova_one_view.tests.<module>`. The project `venv` already has the dependencies; there is no `pytest`.
**Scope:** Backend only. No frontend changes are needed.

All code paths below are relative to `venv/doova_one_view/doova_one_view/`.

## Goal

1. Fix five small bugs in the agent.
2. Fix why users must ask the agent several times to get a correct answer.

The second goal comes from a real chat, "Conatus Total Invoices Request":

| Question | What the agent did | Problem |
|---|---|---|
| "total invoices for conatus" (1st time) | Answered with sales orders: XAF 2,472,535,797 across 2,838 orders | Wrong source, labeled as "invoiced sales" |
| Same question (2nd time) | Answered 2,923 invoices, XAF 3,280,427,050 | Correct only on the second try |
| "list them please" | Refused and offered four options | Claimed a 30-row database limit that is only an internal cap |
| "list the last 20" | Grouped summary with `—` and `SO0642x` placeholders | Incomplete; figures don't reconcile |

## Root causes

### Wrong or inconsistent answers

- **No invoice tool.** `sales_summary` reads `fact_sales_orders`. No tool gives a count and total of customer invoices, which live in `fact_account_moves`.
- **No record-listing tool.** No tool lists orders or invoices row by row.
- **The SQL fallback drops its rows.** `ask_database_custom_question` returns only a prose summary. The model sees at most 30 rows, and the summary is capped at 1,200 tokens. The main agent never sees the real rows, so it fills gaps itself.
- **The SQL fallback ignores the selected company.** The tool has no company setting, although the prompt says every tool call must pass one.
- **The SQL fallback rejects normal questions.** The blocked-word check also runs on the English question, so "analyze", "update", "create" or "copy" cause a refusal.

### Prompt problems (`api/agent/prompts.py`)

- It names 5 tools that don't exist, 10 mentions in total: `get_cash_flow_statement`, `get_payment_reconciliation`, `get_period_comparison_pnl`, `get_revenue_segmentation`, `get_working_capital_efficiency`.
- It says 43 tools; 68 are defined.
- It forces a `tenant_profile` call before any figure, although the currency is already in the prompt. This adds a step to every question.
- It has no rule for listing records, so the model offers menus instead.

### Token usage is unreliable

- `api/agent/routes.py:962` reads the fast agent's usage even when the web search agent answered. This is the likely cause of identical usage on different replies, if web search was on for that chat. It has not been confirmed against logs.
- Agents are shared across requests, and their token counters are reset per run. Overlapping requests can mix up the numbers.

## Phase 0: Set up testing

Tests cannot run yet: the dependencies are not installed and `settings.py` is missing from the working copy.

1. Restore these from GitHub: `settings.py`, `asgi.py`, `urls.py`, `manage.py`, `requirements.txt`, `.gitignore`. Do **not** restore `.env`.
2. Create a `.venv` and install the requirements.
3. Put the database login in `venv/doova_one_view/.env.local` and make sure Git ignores it. Confirm how `settings.py` loads its environment first.
4. Work on a new branch.
5. Run the existing tests and record what already fails, as a baseline.

Local database: Postgres 18 on `localhost:5432`, database `odoo` (migrated to `0044`, with real data). Unit tests use a temporary `test_odoo` database.

## Phase 1: Small fixes

| # | Fix | File | Test |
|---|---|---|---|
| 1.1 | Import `logger`. Both files use it without importing it, so the error handler itself crashes. | `api/agent/session_manager.py:120`, `api/agent/langchain_agent.py:284` | Session is still deleted when attachment cleanup fails; the iteration-limit path doesn't crash |
| 1.2 | Replace the undefined `current_year`. On a bad date, reset both trend dates to today. Only an impossible date in the prompt reaches this code. | `api/agent/tools_refactored/reporting/generate_report_tool.py:253` | A bad date raises no `NameError` |
| 1.3 | Delete `resolve_company_name`. It has a wrong `%(cid)s` placeholder and no callers. | `api/agent/tools_refactored/common.py:18` | Existing tests pass |
| 1.4 | Correct `debit_move_id` / `credit_move_id` to `debit_move_line_id` / `credit_move_line_id`. An audit found no other wrong names among columns containing an underscore. | `api/agent/sql_agent.py` | New test compares the notes to the models, with no database needed |

## Phase 2: Plan fallback

`create_plan` calls `json.loads` on the reply. With adaptive thinking the reply can be a list of blocks, and any failure returns an empty stub plan that the user is then asked to approve.

1. Move `_extract_json_block` to `api/agent/utils.py`. Keep it importable from `routes.py`, because `tests/test_agent_performance_extended.py` imports it from there.
2. In `create_plan` (`api/agent/reasoning.py`), join the text blocks, parse them and require a non-empty `steps` list. Retry once. If it still fails, return a clear failure and save no plan.
3. Fix the background retry path (`routes.py:397-421`). It reads `objective` and `phases`, but the prompt produces `strategic_objective` and `steps`. It also never sets `plan_created_at`, so those plans never expire.
4. **Proposed addition:** save only the changed fields at `routes.py` lines 699, 714, 755 and 1070, because a full save can overwrite newer session data. Clear `plan_created_at` after a plan runs.
5. **Proposed addition:** count a message as approval only if it is 8 words or fewer and is not a question. Today, "what is a good margin?" approves a pending plan because it contains "good". A word limit alone is not enough, since that message is only five words, so questions (a `?` or `؟`, or a question word first) are also rejected. Implemented as `is_plan_approval` in `routes.py`.
6. **Added during implementation:** a model reply that stopped because of `max_tokens` is never accepted as a plan. The extractor closes unfinished brackets, which would turn a cut-off reply into a plan with only its first steps.

**Tests:** plain JSON, fenced JSON, block lists, cut-off JSON and garbage (no plan saved), and "what is a good margin?" with a plan pending.

**Behavior change:** a failed plan now shows an error message, not an empty plan to approve.

## Phase 3: Chat answers

| # | Change | Main files |
|---|---|---|
| 3.1 | SQL fallback returns the real rows and row count, and uses the selected companies. The blocked-word check stays on the SQL but no longer runs on the English question. | `api/agent/sql_agent.py`, `api/agent/langchain_tools.py` |
| 3.2 | Add `list_records` for sales orders, purchase orders, customer invoices, credit notes and vendor bills. It takes limit, offset, date range, partner and sort, and returns the true total. It uses `run_query` with the filter builders and refuses an empty tenant scope. | `api/agent/tools_refactored/`, `api/agent/langchain_tools.py` |
| 3.3 | Add `invoice_summary`, showing invoices, credit notes and the net total separately, from `fact_account_moves`. | `api/agent/tools_refactored/finance.py`, `api/agent/langchain_tools.py` |
| 3.4 | Prompt: invoices come from accounting and orders from sales; list when asked; no menus or placeholder cells. Fix the tool names and count. Limit `tenant_profile` to benchmark questions. | `api/agent/prompts.py` |
| 3.5 | The server inserts the table itself, so the model never retypes rows. Voice mode gets a short sentence instead of a table. | `api/agent/langchain_agent.py`, `api/agent/web_search_agent.py` |
| 3.6 | Report token usage from the agent that actually ran, using a per-run counter. Add usage tracking to the web search agent. Keep the shared agents, since rebuilding one per request is wasteful. Update all 5 usage call sites in `routes.py`. | `api/agent/langchain_agent.py`, `api/agent/web_search_agent.py`, `api/agent/routes.py` |

**Limits:** up to 100 rows in chat. Above that, show the first 100 rows and the true total.

**Tests:**
- Invoice questions use `invoice_summary`, and the answer says "invoices".
- "List the last 20" returns exactly 20 real rows.
- Asking for 3,000 records shows the first 100 and the true total.
- Company scope reaches the SQL fallback.
- A question containing "analyze" is no longer refused, and unsafe SQL still is.
- Two overlapping requests keep separate usage.

**Notes:**
- New tools are added to `agent_tools`. The forecast and audit agents have their own tool lists and won't get them automatically.
- Table headers are in English unless translated, so Arabic, French and Spanish labels need a decision during 3.5.

## Phase 4: Excel export (deferred)

Do this after the report-access security fix. `/reports/{filename}` currently has no login, so exports would be downloadable by anyone with the filename.

- Add a generic row exporter. `api/agent/excel_exporter.py` only builds a fixed 3-tab report and is only used in tests.
- Change `/reports/{filename}`, which always returns the PDF type.
- Extend file cleanup, which only removes `*.pdf`.
- Suggested export limit: 50,000 rows.

## Final check

Replay the questions from the Conatus chat on real data and compare the answers with Odoo.

- Use a copy of the database (`odoo_check`), because the replay saves chat sessions and messages.
- This step needs an Anthropic API key.

## Decisions

| Decision | Recommendation | Status |
|---|---|---|
| Should the invoice headline be net of credit notes? | Yes, with invoices and credit notes also shown separately | Awaiting confirmation |
| Include Phase 2 steps 4 and 5? | Yes | Awaiting confirmation |
| Defer the Excel export? | Yes | Awaiting confirmation |

## Risks

- **Prompt changes (3.4)** affect every answer, so the behavior tests need a rerun afterwards.
- **Prompt caching:** editing the system prompt or tool list invalidates the cache once.
- **More tools** add tokens to every call.
- **Model pricing:** the cost table in `api/agent/langchain_agent.py` still uses the old rates under the new 5.5 model names, so stored costs may be wrong until those rates are confirmed.

## Out of scope

These were found in review and belong to separate work:

- Tenant access checks on agent routes
- Session ownership and report download access
- Email attachment and recipient limits
- A read-only database role for the SQL agent
- Removing the committed `.env` from GitHub and rotating its secrets
- Removing the made-up sample rows in `excel_exporter.py`
- Attachment routing: `routes.py:645` sets EXECUTE, then lines 654-669 overwrite it

## Implementation notes (2026-11-09)

**Phase 3 as built**

- `tools_refactored/records.py`: `get_invoice_summary_tool` and `list_records_tool`. Both refuse to run without a tenant. They are registered in `langchain_tools.py` as `invoice_summary` and `list_records`, and neither inherits the session's remembered date window (so "list the last 20" is not silently limited to an earlier quarter).
- `table_sink.py`: a tool renders its table and gets a marker back; the final reply has the marker replaced with the exact table (appended if the model forgot it, removed in voice mode). Wired into `langchain_agent.py` and `web_search_agent.py`.
- `sql_agent.py`: returns up to 100 real rows and the true row count; respects the selected company; only refuses requests that plainly ask to change data (the generated SQL is still checked by `is_safe_read_only_sql`).
- `prompts.py`: invoices vs orders, list-the-records and answer-don't-ask rules; stale tool names and the "43 tools" count removed; `tenant_profile` is no longer forced before every figure.
- Token usage: `run()` and `create_plan()` use a fresh counter per call and fill an optional `usage_out` dict. `routes.py` reads usage from that dict instead of from the shared agent, and the web search agent now records usage too.
- Limits: 100 rows per page in chat. Larger lists show the first page and the true total; the Excel export stays deferred (Phase 4).

**Checked without calling the model**

- Both tools were run against the local `odoo` database (read-only) and match the Conatus chat: 2,923 invoices totalling 3,280,427,050 XAF, plus 6 credit notes of 13,913,000 XAF (net 3,266,514,050), and 2,838 confirmed orders totalling 2,472,535,797 XAF. The "9,300,000,000" figure in that chat was wrong; the real value is 9,302,000.
- Per-run counters and the table store were checked through LangChain's real `AgentExecutor` with a fake model.

**Still to do**: replay the Conatus questions against the live model and compare with the figures above (costs roughly 0.4 USD per question).

**Test totals**: 255 tests, the same 50 old-interface errors as the baseline, no new failures.

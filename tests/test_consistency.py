"""Offline tests for the deterministic consistency guards (no LLM needed)."""
from app import consistency
from app.schemas import AgentContext, Plan, Section, Task
from app.tools import _budget, _timeline, context_block, get_mock_data


def make_ctx(**plan_fields):
    tasks = [
        Task(title="Data", tool="get_mock_data", description="x", data_type="budget"),
        Task(title="Write", tool="write_section", description="x"),
    ]
    plan = Plan(doc_type="proposal", title="T", tasks=tasks, **plan_fields)
    return AgentContext(request="r", plan=plan)


def test_plan_numbers_are_parsed_leniently():
    plan = make_ctx(timeline_weeks="4 weeks", budget_usd="$50,000").plan
    assert (plan.timeline_weeks, plan.budget_usd) == (4, 50000)
    plan = make_ctx(timeline_weeks="unknown", budget_usd=-5).plan
    assert (plan.timeline_weeks, plan.budget_usd) == (None, None)


def test_timeline_fits_requested_weeks():
    for weeks in (1, 3, 4, 5, 8, 13, 26):
        fitted = consistency.fit_timeline(_timeline(), weeks)
        assert sum(p["duration_weeks"] for p in fitted["phases"]) == weeks == fitted["total_weeks"]
        assert all(p["duration_weeks"] >= 1 for p in fitted["phases"])


def test_timeline_untouched_without_weeks():
    assert consistency.fit_timeline(_timeline(), None) == _timeline()


def test_budget_scales_to_exact_total():
    for total in (91300, 20000, 123457):
        scaled = consistency.scale_budget(_budget(), total)
        assert sum(i["amount_usd"] for i in scaled["line_items"]) == total == scaled["total_usd"]


def test_get_mock_data_follows_plan():
    ctx = make_ctx(timeline_weeks=4, budget_usd=40000)
    timeline = get_mock_data(Task(title="t", tool="get_mock_data", description="x", data_type="timeline"), ctx)
    budget = get_mock_data(Task(title="b", tool="get_mock_data", description="x", data_type="budget"), ctx)
    assert timeline["total_weeks"] == 4 and budget["total_usd"] == 40000


def test_fixed_figures_reach_the_prompt():
    assert "4 weeks" in context_block(make_ctx(timeline_weeks=4, budget_usd=40000))
    assert "FIXED FIGURES" not in context_block(make_ctx())


def _table(rows, columns=("Phase", "Duration (weeks)", "Estimated Cost (USD)")):
    return Section(heading="Budget", columns=list(columns), rows=rows)


def test_table_total_is_enforced_like_the_real_failure():
    ctx = make_ctx()
    ctx.data["budget"] = {"total_usd": 91300}
    table = _table([["A", "1", "5000"], ["B", "1", "5000"], ["C", "1", "30000"], ["D", "1", "56300"]])  # sums to 96,300
    assert consistency.enforce_budget_total(ctx, table)
    body, last = table.rows[:-1], table.rows[-1]
    assert sum(int(r[2]) for r in body) == 91300
    assert last[0] == "Total" and last[2] == "91300"  # a total row is added when missing


def test_table_keeps_currency_format_and_fixes_total_row():
    ctx = make_ctx()
    ctx.data["budget"] = {"total_usd": 100000}
    table = _table([["A", "1", "$30,000"], ["B", "1", "$60,000"], ["Total", "2", "$90,000"]])
    consistency.enforce_budget_total(ctx, table)
    assert [r[2] for r in table.rows][2] == "$100,000"
    assert sum(int(r[2].replace("$", "").replace(",", "")) for r in table.rows[:2]) == 100000


def test_unrelated_or_unparseable_tables_are_left_alone():
    ctx = make_ctx()
    ctx.data["budget"] = {"total_usd": 91300}
    far = _table([["A", "1", "1000"], ["B", "1", "2000"]])  # nowhere near the budget
    text = _table([["A", "1", "TBD"], ["B", "1", "50000"]])
    no_cost = _table([["A", "1"], ["B", "2"]], columns=("Phase", "Weeks"))
    for table in (far, text, no_cost):
        before = [list(r) for r in table.rows]
        assert not consistency.enforce_budget_total(ctx, table)
        assert table.rows == before
    assert not consistency.enforce_budget_total(make_ctx(), _table([["A", "1", "5"], ["B", "1", "6"]]))  # no budget data

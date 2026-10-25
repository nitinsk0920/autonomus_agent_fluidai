"""Offline tests for the polish fixes found while testing the complex request."""
from app.planner import _drop_summary_tasks
from app.schemas import Plan, Section, Task


def test_inline_bullets_are_split():
    section = Section(
        heading="KPIs",
        bullets=["KPIs mapped to checkpoints: \u2022 Week 1 -- Design \u2022 Week 2 -- Build", "- plain bullet", "  "],
    )
    assert section.bullets == ["KPIs mapped to checkpoints:", "Week 1 -- Design", "Week 2 -- Build", "plain bullet"]


def _plan(*titles_and_tools):
    tasks = [Task(title=t, tool=tool, description="x", data_type="budget" if tool == "get_mock_data" else None)
             for t, tool in titles_and_tools]
    return Plan(doc_type="proposal", title="T", tasks=tasks)


def test_duplicate_summary_task_is_dropped():
    plan = _plan(("Budget", "get_mock_data"), ("Executive Overview (auto-generated)", "write_section"),
                 ("Migration Strategy", "write_section"), ("Cost Table", "build_table"))
    _drop_summary_tasks(plan)
    assert [t.title for t in plan.tasks] == ["Budget", "Migration Strategy", "Cost Table"]


def test_summary_filter_never_empties_the_plan():
    plan = _plan(("Budget", "get_mock_data"), ("Executive Summary", "write_section"))
    _drop_summary_tasks(plan)
    assert len(plan.tasks) == 2  # dropping it would leave no content task, so it is kept

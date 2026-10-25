"""Step 2 of the workflow: the LLM writes its own execution plan (the TODO list)."""
import logging

from pydantic import ValidationError

from app import llm, tools
from app.errors import PlanningError
from app.schemas import Plan

log = logging.getLogger("agent.planner")

_TOOL_LINES = "\n".join(f"- {name}: {meta['description']}" for name, meta in tools.TOOLS.items())

PLAN_SYSTEM = (
    "You are the PLANNING module of an autonomous document-writing agent. "
    "Read the user's request and produce an execution plan as JSON only.\n\n"
    "The agent can use exactly these tools:\n" + _TOOL_LINES + "\n\n"
    "Rules:\n"
    "1. NEVER ask the user questions. If the request is ambiguous or incomplete, choose sensible defaults "
    "and list them in \"assumptions\".\n"
    "2. If requirements conflict (e.g. tiny budget vs tight deadline vs full compliance), list each one in "
    "\"conflicts\" with a concrete \"resolution\" (e.g. phased rollout, reduced scope) that the document will follow.\n"
    "3. If no document type is given, pick the best one: project_plan, proposal, business_report, "
    "technical_design, sop, meeting_minutes or product_spec.\n"
    "4. Create 5-9 tasks in logical order. Fetch data (get_mock_data) BEFORE the sections that need it. "
    "Do NOT add an executive summary task - the agent adds one automatically.\n"
    "5. Each task needs a clear \"description\" of what the section must contain.\n\n"
    "Return JSON in exactly this shape:\n"
    "{\n"
    '  "doc_type": "project_plan",\n'
    '  "title": "Professional document title",\n'
    '  "audience": "Who will read it",\n'
    '  "assumptions": ["..."],\n'
    '  "conflicts": [{"issue": "...", "resolution": "..."}],\n'
    '  "tasks": [\n'
    '    {"id": 1, "title": "...", "tool": "get_mock_data", "data_type": "budget", "description": "..."},\n'
    '    {"id": 2, "title": "...", "tool": "write_section", "data_type": null, "description": "..."}\n'
    "  ]\n"
    "}"
)


def create_plan(request: str) -> Plan:
    """Ask the LLM for a plan. If it fails validation, tell it what was wrong and retry once."""
    feedback = ""
    last_problem = ""
    for attempt in (1, 2):
        data = llm.chat_json(PLAN_SYSTEM, f"USER REQUEST:\n{request}{feedback}", max_tokens=2000, label="plan")
        try:
            plan = Plan(**data)
        except ValidationError as exc:
            last_problem = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            log.warning("Plan attempt %d invalid: %s", attempt, last_problem)
            feedback = f"\n\nYour previous plan was invalid ({last_problem}). Fix it and return the full JSON again."
            continue
        for number, task in enumerate(plan.tasks, start=1):
            task.id = number  # never trust LLM numbering
        log.info("Plan ready: '%s' (%s) with %d tasks", plan.title, plan.doc_type, len(plan.tasks))
        return plan
    raise PlanningError(f"Could not create a valid plan: {last_problem}")

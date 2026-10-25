"""The agent orchestrator: validate -> plan -> execute -> summarise -> reflect -> build docx -> respond."""
import logging
import time

from app import config, tools
from app.docbuilder import build_docx
from app.errors import AgentError
from app.planner import create_plan
from app.reflection import reflect_and_revise
from app.schemas import AgentContext, AgentResponse, Section

log = logging.getLogger("agent")


def execute_plan(ctx: AgentContext) -> None:
    """Step 3: run every task with its tool. A failing task is recorded, not fatal."""
    for task in ctx.plan.tasks:
        log.info("Task %d/%d [%s] %s", task.id, len(ctx.plan.tasks), task.tool, task.title)
        try:
            result = tools.TOOLS[task.tool]["fn"](task, ctx)
            if task.tool == "get_mock_data":
                ctx.data[task.data_type] = result  # later tasks can use this data
            else:
                ctx.sections.append(result)
            task.status = "done"
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)[:300]
            log.warning("Task %d failed: %s", task.id, exc)


def _make_summary(ctx: AgentContext):
    try:
        return tools.write_summary(ctx)
    except Exception as exc:  # fall back to a plain summary instead of failing the request
        log.warning("Summary generation failed, using fallback: %s", exc)
        return Section(
            heading="Executive Summary",
            paragraphs=[f"This {ctx.plan.doc_type.replace('_', ' ')} responds to the following request: {ctx.request}"],
        )


def run_agent(request: str, request_id: str) -> AgentResponse:
    started = time.time()

    plan = create_plan(request)                       # 2. PLAN
    ctx = AgentContext(request=request, plan=plan)
    execute_plan(ctx)                                 # 3. EXECUTE
    if not ctx.sections:
        raise AgentError("Every content task failed, so there is nothing to put in the document.")
    ctx.summary = _make_summary(ctx)
    reflection = reflect_and_revise(ctx)              # 4. REFLECT
    if reflection.verdict == "revised":
        ctx.summary = _make_summary(ctx)              # keep the summary in sync with the repaired draft
    build_docx(ctx, config.OUTPUT_DIR, request_id)    # 5. BUILD DOCX

    done = sum(1 for t in plan.tasks if t.status == "done")
    all_ok = done == len(plan.tasks)
    message = (
        f"Created '{plan.title}' ({plan.doc_type.replace('_', ' ')}) with {len(ctx.sections)} sections. "
        f"{done}/{len(plan.tasks)} planned tasks succeeded. Reflection: {reflection.verdict}."
    )
    return AgentResponse(                             # 6. RESPOND
        request_id=request_id,
        status="completed" if all_ok else "completed_with_errors",
        message=message,
        plan=plan,
        reflection=reflection,
        download_url=f"/download/{request_id}",
        duration_seconds=round(time.time() - started, 1),
    )

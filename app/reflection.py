"""Step 4 of the workflow: REFLECTION (the one engineering improvement).

After the draft is written, a second LLM call acts as a strict reviewer. It compares the
draft against the ORIGINAL request and the agent's own plan. If it finds real problems, the
agent repairs only the affected sections - once - and reports what it changed.
"""
import logging
from typing import List

from app import llm, tools
from app.schemas import AgentContext, Reflection, ReviewIssue

log = logging.getLogger("agent.reflection")

MAX_ISSUES = 3

REVIEW_SYSTEM = (
    "You are a strict reviewer of an AI-generated business document. Compare the DRAFT with the "
    "ORIGINAL REQUEST and the PLAN. Check:\n"
    "1. Every requirement and constraint in the request is addressed.\n"
    "2. Each listed conflict is visibly resolved in the content (not ignored).\n"
    "3. The content is specific, not vague or generic filler.\n"
    "4. Numbers (budgets, dates, durations) are consistent across sections.\n"
    "5. No important section is missing (tasks marked FAILED have no content).\n"
    "Reply with JSON only:\n"
    '{"verdict": "pass" or "revise", "issues": [{"section_index": 0, "problem": "...", "fix": "..."}]}\n'
    "section_index is the [number] of the faulty section, or null if a whole new section is missing. "
    f"Report at most {MAX_ISSUES} issues, only real ones. If the draft is good, return verdict pass and an empty list."
)


def _review(ctx: AgentContext) -> List[ReviewIssue]:
    plan = ctx.plan
    failed = [t.title for t in plan.tasks if t.status == "failed"]
    parts = [
        f"ORIGINAL REQUEST:\n{ctx.request}",
        "PLAN:\n"
        f"Assumptions: {plan.assumptions}\n"
        f"Conflicts and resolutions: {[c.model_dump() for c in plan.conflicts]}\n"
        f"Planned tasks: {[t.title for t in plan.tasks]}\n"
        f"FAILED tasks: {failed or 'none'}",
        "EXECUTIVE SUMMARY:\n" + (ctx.summary.as_text(500) if ctx.summary else "(none)"),
        "DRAFT SECTIONS:\n" + "\n\n".join(f"[{i}] {s.as_text(600)}" for i, s in enumerate(ctx.sections)),
    ]
    data = llm.chat_json(REVIEW_SYSTEM, "\n\n".join(parts), max_tokens=1000, label="review")

    issues = []
    for raw in (data.get("issues") or [])[:MAX_ISSUES]:
        if not isinstance(raw, dict) or not raw.get("problem"):
            continue
        index = raw.get("section_index")
        index = index if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(ctx.sections) else None
        issues.append(
            ReviewIssue(
                section_index=index,
                section=ctx.sections[index].heading if index is not None else None,
                problem=str(raw["problem"]),
                fix=str(raw.get("fix") or raw["problem"]),
            )
        )
    return issues


def reflect_and_revise(ctx: AgentContext) -> Reflection:
    """Review the draft, repair flagged sections once, and return a report for the API response."""
    try:
        issues = _review(ctx)
    except Exception as exc:  # reflection must never break the whole request
        log.warning("Reflection skipped: %s", exc)
        return Reflection(verdict="skipped", error=str(exc)[:300])

    if not issues:
        log.info("Reflection: draft passed review")
        return Reflection(verdict="pass")

    revised, added = [], []
    for issue in issues:
        try:
            if issue.section_index is not None:
                old = ctx.sections[issue.section_index]
                ctx.sections[issue.section_index] = tools.revise_section(ctx, old, issue.problem, issue.fix)
                if old.heading not in revised:
                    revised.append(old.heading)
            else:
                new = tools.add_missing_section(ctx, issue.problem, issue.fix)
                ctx.sections.append(new)
                added.append(new.heading)
        except Exception as exc:
            log.warning("Could not apply fix for '%s': %s", issue.problem, exc)

    verdict = "revised" if (revised or added) else "issues_unresolved"
    log.info("Reflection: %d issue(s) found, revised=%s, added=%s", len(issues), revised, added)
    return Reflection(verdict=verdict, issues=issues, sections_revised=revised, sections_added=added)

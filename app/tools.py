"""The tools the agent can call.

Each tool has the same signature: tool(task, ctx) -> result.
  - get_mock_data  returns a dict of illustrative data (stored in ctx.data)
  - write_section  returns a prose Section   (appended to ctx.sections)
  - build_table    returns a table Section   (appended to ctx.sections)

To add a new tool: write the function and add it to the TOOLS registry at the
bottom (also add its name to ToolName in schemas.py). The planner prompt is
generated from the registry, so it learns about the tool automatically.
"""
import json
import logging

from app import llm
from app.schemas import AgentContext, Section, Task

log = logging.getLogger("agent.tools")


# ----------------------------------------------------------------------------
# Tool 1: get_mock_data (deterministic, no LLM)
# ----------------------------------------------------------------------------
def _budget() -> dict:
    items = [
        ("Personnel", 45000),
        ("Software & Licences", 12000),
        ("Infrastructure & Hosting", 18000),
        ("Training & Change Management", 8000),
    ]
    subtotal = sum(amount for _, amount in items)
    contingency = round(subtotal * 0.10)
    line_items = [{"category": name, "amount_usd": amount} for name, amount in items]
    line_items.append({"category": "Contingency (10%)", "amount_usd": contingency})
    return {"currency": "USD", "line_items": line_items, "total_usd": subtotal + contingency}


def _timeline() -> dict:
    phases = [
        ("Discovery & Requirements", 2, "Requirements signed off"),
        ("Design & Planning", 2, "Design approved"),
        ("Build & Integration", 5, "Working release candidate"),
        ("Testing & UAT", 2, "UAT sign-off"),
        ("Launch & Hypercare", 2, "Go-live and stabilisation"),
    ]
    return {
        "phases": [{"phase": p, "duration_weeks": w, "milestone": m} for p, w, m in phases],
        "total_weeks": sum(w for _, w, _ in phases),
    }


def _team() -> dict:
    return {
        "roles": [
            {"role": "Project Manager", "allocation": "50%", "responsibility": "Planning, reporting, risk tracking"},
            {"role": "Technical Lead", "allocation": "100%", "responsibility": "Architecture and delivery"},
            {"role": "Engineers (2)", "allocation": "100%", "responsibility": "Build and integration"},
            {"role": "Business Analyst", "allocation": "50%", "responsibility": "Requirements and acceptance criteria"},
            {"role": "QA Engineer", "allocation": "50%", "responsibility": "Test planning and execution"},
        ]
    }


def _risks() -> dict:
    return {
        "risks": [
            {"risk": "Scope creep", "likelihood": "High", "impact": "Medium", "mitigation": "Formal change control"},
            {"risk": "Key person unavailable", "likelihood": "Medium", "impact": "High", "mitigation": "Cross-training and documentation"},
            {"risk": "Integration delays", "likelihood": "Medium", "impact": "High", "mitigation": "Early technical spikes"},
            {"risk": "Budget overrun", "likelihood": "Medium", "impact": "High", "mitigation": "10% contingency, monthly cost review"},
            {"risk": "Low user adoption", "likelihood": "Medium", "impact": "Medium", "mitigation": "Training and phased rollout"},
        ]
    }


def _kpis() -> dict:
    return {
        "kpis": [
            {"metric": "On-time milestone delivery", "target": ">= 90%"},
            {"metric": "Budget variance", "target": "within +/-10%"},
            {"metric": "User satisfaction (CSAT)", "target": ">= 4.2 / 5"},
            {"metric": "Critical defects at launch", "target": "0"},
        ]
    }


MOCK_BUILDERS = {"budget": _budget, "timeline": _timeline, "team": _team, "risks": _risks, "kpis": _kpis}


def get_mock_data(task: Task, ctx: AgentContext) -> dict:
    return MOCK_BUILDERS[task.data_type]()


# ----------------------------------------------------------------------------
# Shared prompt helper
# ----------------------------------------------------------------------------
def context_block(ctx: AgentContext) -> str:
    """Everything the LLM should know when writing: request, plan decisions, data, progress."""
    plan = ctx.plan
    lines = [
        f"ORIGINAL REQUEST: {ctx.request}",
        f"DOCUMENT: {plan.title} ({plan.doc_type}) for {plan.audience}",
    ]
    if plan.assumptions:
        lines.append("ASSUMPTIONS:\n" + "\n".join(f"- {a}" for a in plan.assumptions))
    if plan.conflicts:
        lines.append(
            "CONFLICT RESOLUTIONS (the document must follow these):\n"
            + "\n".join(f"- {c.issue} -> {c.resolution}" for c in plan.conflicts)
        )
    if ctx.data:
        lines.append(
            "DATA GATHERED (illustrative mock data - present figures as estimates, adapt them to the request):\n"
            + json.dumps(ctx.data)[:3000]
        )
    if ctx.sections:
        lines.append("SECTIONS ALREADY WRITTEN (do not repeat): " + "; ".join(s.heading for s in ctx.sections))
    return "\n\n".join(lines)


# ----------------------------------------------------------------------------
# Tool 2: write_section (LLM)
# ----------------------------------------------------------------------------
PROSE_SYSTEM = (
    "You are a professional business writer inside an autonomous document agent. "
    "Write ONE section of a business document. Reply with JSON only, in this shape:\n"
    '{"heading": "string", "paragraphs": ["string"], "bullets": ["string"]}\n'
    "Rules: 1-3 short paragraphs (2-4 sentences each); bullets are optional (max 6); be specific and "
    "concrete, no filler; use the supplied data where relevant and call figures estimates; follow the "
    "stated assumptions and conflict resolutions; do not repeat other sections."
)

TABLE_SYSTEM = (
    "You are a professional business writer inside an autonomous document agent. "
    "Build ONE table section of a business document. Reply with JSON only, in this shape:\n"
    '{"heading": "string", "intro": "one sentence introducing the table", '
    '"columns": ["string"], "rows": [["string"]]}\n'
    "Rules: 2-6 columns, 3-10 rows, short cell text, every row has one cell per column. Use the supplied "
    "data where relevant (keep numbers consistent with it) and adapt it to the request and its constraints."
)


def _generate_prose(ctx: AgentContext, title: str, instruction: str, label: str) -> Section:
    user = f"{context_block(ctx)}\n\nSECTION TO WRITE\nTitle: {title}\nInstructions: {instruction}"
    data = llm.chat_json(PROSE_SYSTEM, user, max_tokens=1200, label=label)
    data.setdefault("heading", title)
    section = Section(**data)
    if not (section.paragraphs or section.bullets):
        raise ValueError("The model returned an empty section")
    return section


def _generate_table(ctx: AgentContext, title: str, instruction: str, label: str) -> Section:
    user = f"{context_block(ctx)}\n\nTABLE TO BUILD\nTitle: {title}\nInstructions: {instruction}"
    data = llm.chat_json(TABLE_SYSTEM, user, max_tokens=1200, label=label)
    data.setdefault("heading", title)
    if data.get("intro"):
        data["paragraphs"] = [data["intro"]]
    section = Section(**data)
    if not (section.columns and section.rows):
        raise ValueError("The model returned an empty table")
    return section


def write_section(task: Task, ctx: AgentContext) -> Section:
    return _generate_prose(ctx, task.title, task.description, label="write_section")


def build_table(task: Task, ctx: AgentContext) -> Section:
    return _generate_table(ctx, task.title, task.description, label="build_table")


# ----------------------------------------------------------------------------
# Used by the agent after execution, and by reflection to repair the draft
# ----------------------------------------------------------------------------
SUMMARY_SYSTEM = (
    "You write the EXECUTIVE SUMMARY of a business document. Reply with JSON only, in this shape:\n"
    '{"heading": "Executive Summary", "paragraphs": ["string"], "bullets": ["string"]}\n'
    "Rules: 1-2 short paragraphs plus 3-5 bullets with the key points. Mention the headline decisions "
    "(assumptions and how conflicts were resolved). Only use facts that appear in the document content."
)


def write_summary(ctx: AgentContext) -> Section:
    content = "\n\n".join(s.as_text(400) for s in ctx.sections)
    user = f"{context_block(ctx)}\n\nDOCUMENT CONTENT:\n{content}"
    data = llm.chat_json(SUMMARY_SYSTEM, user, max_tokens=900, label="summary")
    data["heading"] = "Executive Summary"
    section = Section(**data)
    if not (section.paragraphs or section.bullets):
        raise ValueError("The model returned an empty summary")
    return section


def revise_section(ctx: AgentContext, section: Section, problem: str, fix: str) -> Section:
    """Rewrite one existing section to fix a problem found by the reviewer."""
    instruction = (
        f"Revise this existing section. Problem found by the reviewer: {problem} "
        f"Required fix: {fix} Keep what was good. Existing content: {section.model_dump_json()}"
    )
    generate = _generate_table if section.columns else _generate_prose
    return generate(ctx, section.heading, instruction, label="revise_section")


def add_missing_section(ctx: AgentContext, problem: str, fix: str) -> Section:
    """Write a brand-new section the reviewer says is missing."""
    instruction = f"The reviewer found a gap: {problem} Add a section that does this: {fix}"
    return _generate_prose(ctx, "Additional Section", instruction, label="add_section")


# ----------------------------------------------------------------------------
# Registry: the planner prompt is built from this
# ----------------------------------------------------------------------------
TOOLS = {
    "get_mock_data": {
        "fn": get_mock_data,
        "description": 'fetches illustrative data. Needs "data_type", one of: budget, timeline, team, risks, kpis.',
    },
    "write_section": {
        "fn": write_section,
        "description": "an LLM writes one prose section (paragraphs and bullets).",
    },
    "build_table": {
        "fn": build_table,
        "description": "an LLM builds one table section (columns and rows).",
    },
}

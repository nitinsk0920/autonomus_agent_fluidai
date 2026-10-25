"""Deterministic guards for figures an LLM must not get wrong.

LLMs are bad at arithmetic and drift away from stated constraints, so numbers are
handled in code:
  - fit_timeline / scale_budget : make the mock data match the plan's duration and budget
  - fixed_figures               : tell every writing prompt which figures are fixed
  - enforce_budget_total        : after a table is generated, make its cost column add up
"""
import logging
import re
from typing import Optional

from app.schemas import AgentContext, Plan, Section

log = logging.getLogger("agent.consistency")

_AMOUNT = re.compile(r"^\s*([$€£₹]?)\s*(\d[\d,]*(?:\.\d+)?)\s*$")
_COST_HEADERS = ("cost", "usd", "budget", "amount", "$")


# ----------------------------------------------------------------------------
# Mock data that follows the plan
# ----------------------------------------------------------------------------
def fit_timeline(data: dict, weeks: Optional[int]) -> dict:
    """Rescale the mock timeline so its phases add up to exactly `weeks`."""
    phases = data["phases"]
    n = len(phases)
    if not weeks or weeks == data["total_weeks"]:
        return data
    if weeks >= n:  # keep every phase, share the extra weeks in proportion to the original lengths
        weights = [p["duration_weeks"] for p in phases]
        extra = weeks - n
        shares = [extra * w / sum(weights) for w in weights]
        add = [int(s) for s in shares]
        for i in sorted(range(n), key=lambda i: shares[i] - add[i], reverse=True)[: extra - sum(add)]:
            add[i] += 1
        fitted = [{**p, "duration_weeks": 1 + add[i]} for i, p in enumerate(phases)]
    else:  # fewer weeks than phases: merge neighbouring phases, one week each
        size, remainder = divmod(n, weeks)
        fitted, start = [], 0
        for g in range(weeks):
            end = start + size + (1 if g < remainder else 0)
            group = phases[start:end]
            fitted.append(
                {"phase": " + ".join(p["phase"] for p in group), "duration_weeks": 1, "milestone": group[-1]["milestone"]}
            )
            start = end
    return {"phases": fitted, "total_weeks": weeks}


def scale_budget(data: dict, total: Optional[int]) -> dict:
    """Rescale the mock budget so the line items plus 10% contingency equal exactly `total`."""
    if not total:
        return data
    *items, contingency = data["line_items"]
    contingency_amount = round(total / 11)  # total = subtotal * 1.10
    subtotal = total - contingency_amount
    base = sum(i["amount_usd"] for i in items)
    amounts = [round(i["amount_usd"] * subtotal / base) for i in items]
    amounts[0] += subtotal - sum(amounts)  # the first line absorbs rounding so the sum is exact
    line_items = [{"category": i["category"], "amount_usd": a} for i, a in zip(items, amounts)]
    line_items.append({"category": contingency["category"], "amount_usd": contingency_amount})
    return {"currency": data["currency"], "line_items": line_items, "total_usd": total}


def fixed_figures(plan: Plan) -> str:
    """A prompt block listing the figures every section must respect (empty if none are set)."""
    lines = []
    if plan.timeline_weeks:
        lines.append(f"- Total duration: {plan.timeline_weeks} weeks. Never mention any other overall duration.")
    if plan.budget_usd:
        lines.append(f"- Total budget: ${plan.budget_usd:,} (including contingency). Any cost breakdown must sum to this.")
    return ("FIXED FIGURES (never contradict these):\n" + "\n".join(lines)) if lines else ""


# ----------------------------------------------------------------------------
# Post-check on generated tables
# ----------------------------------------------------------------------------
def _parse(cell: str):
    match = _AMOUNT.match(cell)
    if not match:
        return None
    return match.group(1), float(match.group(2).replace(",", "")), "," in match.group(2)


def _format(prefix: str, value: int, commas: bool) -> str:
    return f"{prefix}{value:,}" if commas else f"{prefix}{value}"


def enforce_budget_total(ctx: AgentContext, section: Section) -> bool:
    """If a table's cost column is meant to add up to the budget but doesn't, rescale it in code.

    Only acts when the table clearly attempts the budget total (within 30%), so unrelated
    cost tables are left alone. Returns True when the table was changed.
    """
    budget = ctx.data.get("budget")
    total = budget.get("total_usd") if isinstance(budget, dict) else None
    if not total or not section.columns or len(section.rows) < 2:
        return False
    col = next((i for i, name in enumerate(section.columns) if any(k in name.lower() for k in _COST_HEADERS)), None)
    if col is None:
        return False

    body, total_row = [], None
    for idx, row in enumerate(section.rows):
        if row[0].strip().lower().startswith(("total", "grand total", "sum")):
            total_row = idx
        else:
            body.append(idx)
    parsed = {idx: _parse(section.rows[idx][col]) for idx in body}
    if not body or any(p is None for p in parsed.values()):
        return False  # a cell is not a plain amount, so do not guess

    current = sum(p[1] for p in parsed.values())
    if not 0.7 * total <= current <= 1.3 * total:
        return False

    new = {idx: round(p[1] * total / current) for idx, p in parsed.items()}
    largest = max(new, key=new.get)
    new[largest] += total - sum(new.values())  # exact sum

    changed = False
    for idx, value in new.items():
        prefix, _, commas = parsed[idx]
        text = _format(prefix, value, commas)
        changed |= section.rows[idx][col] != text
        section.rows[idx][col] = text
    prefix, _, commas = parsed[body[0]]
    text = _format(prefix, total, commas)
    if total_row is not None:
        changed |= section.rows[total_row][col] != text
        section.rows[total_row][col] = text
    elif col != 0:  # a board reader should not have to add the column up themselves
        row = [""] * len(section.columns)
        row[0], row[col] = "Total", text
        section.rows.append(row)
        changed = True
    if changed:
        log.info("Table '%s': cost column rescaled to add up to the budget total of %d", section.heading, total)
    return changed

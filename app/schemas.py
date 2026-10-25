"""Pydantic models: API request/response, the agent's plan, and document sections."""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ToolName = Literal["get_mock_data", "write_section", "build_table"]
DataType = Literal["budget", "timeline", "team", "risks", "kpis"]


# ----------------------------------------------------------------------------
# API input (this is the "request validation & guardrails" layer)
# ----------------------------------------------------------------------------
class AgentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Natural-language description of the document you need.",
        examples=["Create a project plan for launching a support chatbot over 3 months."],
    )


# ----------------------------------------------------------------------------
# Document content. LLM output is messy, so validators coerce it into clean shapes.
# ----------------------------------------------------------------------------
class Section(BaseModel):
    heading: str
    paragraphs: List[str] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)  # table header (empty = no table)
    rows: List[List[str]] = Field(default_factory=list)

    @field_validator("paragraphs", "bullets", "columns", mode="before")
    @classmethod
    def _to_str_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    @field_validator("bullets", mode="after")
    @classmethod
    def _split_inline_bullets(cls, items):
        """LLMs sometimes pack several bullets into one string with a bullet character; split them."""
        cleaned = []
        for item in items:
            for part in re.split(r"\s*[•●▪]\s*", item):
                part = re.sub(r"^[-*–]\s+", "", part.strip())
                if part:
                    cleaned.append(part)
        return cleaned

    @field_validator("rows", mode="before")
    @classmethod
    def _to_rows(cls, value):
        rows = []
        for row in value or []:
            if isinstance(row, dict):
                row = list(row.values())
            elif not isinstance(row, (list, tuple)):
                row = [row]
            rows.append([str(cell) for cell in row])
        return rows

    @model_validator(mode="after")
    def _pad_rows(self):
        width = len(self.columns)
        if width:
            self.rows = [(row + [""] * width)[:width] for row in self.rows]
        return self

    def as_text(self, limit: int = 600) -> str:
        """Compact text version, used when showing a section to the reviewer LLM."""
        parts = [f"{self.heading}:"] + self.paragraphs
        if self.columns:
            parts.append(f"[Table: {', '.join(self.columns)} - {len(self.rows)} rows]")
            parts += [" | ".join(row) for row in self.rows[:3]]
        parts += [f"- {bullet}" for bullet in self.bullets]
        text = " ".join(parts)
        return text if len(text) <= limit else text[:limit] + "..."


# ----------------------------------------------------------------------------
# The plan the agent writes for itself
# ----------------------------------------------------------------------------
class Task(BaseModel):
    id: int = 0
    title: str
    tool: ToolName
    description: str
    data_type: Optional[DataType] = None  # only used by get_mock_data
    status: Literal["pending", "done", "failed"] = "pending"
    error: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def _lenient_id(cls, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0  # the planner renumbers tasks anyway

    @field_validator("tool", mode="before")
    @classmethod
    def _clean_tool(cls, value):
        return str(value).strip().lower()

    @field_validator("data_type", mode="before")
    @classmethod
    def _clean_data_type(cls, value):
        text = str(value).strip().lower() if value is not None else ""
        return None if text in ("", "none", "null", "n/a", "na") else text

    @model_validator(mode="after")
    def _data_tool_needs_type(self):
        if self.tool == "get_mock_data" and not self.data_type:
            raise ValueError("get_mock_data tasks need a data_type")
        return self


class Conflict(BaseModel):
    issue: str
    resolution: str


class Plan(BaseModel):
    doc_type: str
    title: str
    audience: str = "Business stakeholders"
    assumptions: List[str] = Field(default_factory=list)
    conflicts: List[Conflict] = Field(default_factory=list)
    timeline_weeks: Optional[int] = None  # total duration, if stated or assumed
    budget_usd: Optional[int] = None  # total budget incl. contingency, if stated or assumed
    tasks: List[Task] = Field(min_length=2, max_length=10)

    @field_validator("timeline_weeks", "budget_usd", mode="before")
    @classmethod
    def _lenient_number(cls, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = value
        else:
            match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
            if not match:
                return None
            number = float(match.group().replace(",", ""))
        return int(number) if number > 0 else None

    @field_validator("assumptions", mode="before")
    @classmethod
    def _assumptions_to_str(cls, value):
        if value is None:
            return []
        return [str(item) for item in (value if isinstance(value, list) else [value])]

    @field_validator("conflicts", mode="before")
    @classmethod
    def _conflicts_from_strings(cls, value):
        fixed = []
        for item in value or []:
            if isinstance(item, str):
                item = {"issue": item, "resolution": "Handled through the stated assumptions."}
            fixed.append(item)
        return fixed

    @model_validator(mode="after")
    def _needs_content_task(self):
        if not any(task.tool != "get_mock_data" for task in self.tasks):
            raise ValueError("plan needs at least one write_section or build_table task")
        return self


# ----------------------------------------------------------------------------
# Reflection result + API response
# ----------------------------------------------------------------------------
class ReviewIssue(BaseModel):
    section_index: Optional[int] = None  # None = a whole section is missing
    section: Optional[str] = None
    problem: str
    fix: str


class Reflection(BaseModel):
    verdict: Literal["pass", "revised", "issues_unresolved", "skipped"]
    issues: List[ReviewIssue] = Field(default_factory=list)
    sections_revised: List[str] = Field(default_factory=list)
    sections_added: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class AgentResponse(BaseModel):
    request_id: str
    status: Literal["completed", "completed_with_errors"]
    message: str
    plan: Plan  # includes every task with its final status
    reflection: Reflection
    download_url: str
    duration_seconds: float


# ----------------------------------------------------------------------------
# Working memory shared by planner, tools, reflection and the doc builder
# ----------------------------------------------------------------------------
@dataclass
class AgentContext:
    request: str
    plan: Plan
    data: Dict[str, Any] = field(default_factory=dict)  # output of get_mock_data tasks
    sections: List[Section] = field(default_factory=list)  # the draft document body
    summary: Optional[Section] = None

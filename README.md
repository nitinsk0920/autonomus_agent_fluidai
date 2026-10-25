# Autonomous Document Agent

`POST /agent` takes a plain-English request. The agent **plans its own TODO list, executes it with tools,
reviews its own draft, and returns a Word (.docx) document.** Built with FastAPI, Groq (free tier) and python-docx.
There is no agent framework: the whole agent is a plain Python loop, so every step is easy to read and explain.

## Run it

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
# 1. open .env and paste your GROQ_API_KEY
# (models default to openai/gpt-oss-120b with openai/gpt-oss-20b as fallback; override with
#  GROQ_MODEL / GROQ_FALLBACK_MODEL in .env - Groq retired the old Llama defaults on 2026-08-16)
uvicorn app.main:app --port 8000
```

Then in a second terminal: `python demo.py` (runs both test inputs), or open http://127.0.0.1:8000/docs.

```bash
curl -X POST http://127.0.0.1:8000/agent -H "Content-Type: application/json" \
     -d '{"request": "Create a project plan for launching a support chatbot over 3 months"}'
```

Offline tests (no key needed, a fake LLM is used): `python -m pytest -q`

## API

| Endpoint | Purpose |
|---|---|
| `POST /agent` `{"request": "..."}` | Runs the agent. Returns the plan (tasks + statuses), assumptions, conflicts, reflection report, `download_url` |
| `GET /download/{request_id}` | Downloads the generated `.docx` |
| `GET /health` | Liveness check |

Errors: `422` invalid input, `503` missing API key, `502` the LLM/planner could not produce a result.

## Workflow

```
POST /agent
  1. VALIDATE   Pydantic: 10-2000 characters, trimmed                      schemas.py
  2. PLAN       LLM writes JSON plan: doc type, assumptions, conflicts,     planner.py
                timeline_weeks, budget_usd, task list. Invalid plan -> error fed back, retried once.
                Duplicate executive-summary tasks are dropped (the agent writes its own)
  3. EXECUTE    Loop over tasks, each calls one tool                        agent.py, tools.py
                get_mock_data -> data (scaled to the plan's weeks and budget)
                write_section / build_table -> sections. Table cost columns are made to add up
                in code (consistency.py). A failed task is marked "failed" and the run continues
  4. REFLECT    A reviewer LLM compares the draft to the original request   reflection.py
                and the plan; flagged sections are rewritten once; the executive summary is
                regenerated if anything changed
  5. BUILD DOCX Title, summary, assumptions box, numbered sections,         docbuilder.py
                tables, header and page-numbered footer
  6. RESPOND    JSON + download link
```

Files: `llm.py` (Groq client, JSON parsing, retry, fallback model), `consistency.py` (deterministic number guards),
`config.py` (.env), `errors.py`.

## The one engineering improvement: Reflection / self-check

* **What:** after drafting, a second LLM call reviews the document against the *original request* and the agent's *own plan*
  (requirements covered? conflicts actually resolved? vague filler? numbers consistent? missing sections?
  nonsensical cost-to-week mappings? overclaiming or unadmitted feasibility risk? duplicated sections?).
  It returns up to 4 issues. The agent rewrites those sections (or adds a missing one) once, then reports what changed.
* **Why:** the first draft is written one section at a time, so no single call sees the whole document. Ambiguous and
  conflicting requests are exactly where such drafts quietly drift. A review pass sees everything together.
* **Improvement:** catches gaps and inconsistencies automatically, and also repairs sections whose task failed.
  It is visible in the response (`reflection.issues`, `sections_revised`, `sections_added`).
  If the reviewer itself fails, the run still completes (`verdict: "skipped"`).

Supporting reliability: `llm.py` has JSON mode, fence/chatter stripping, retry honouring Groq's Retry-After, and fallback
to a smaller model (a retired or unknown model id skips straight to the fallback). `consistency.py` exists because the
reviewer is an LLM and LLMs are poor at arithmetic: sums, durations and budget figures are enforced in code.

## Adding a tool
Write `my_tool(task, ctx)` in `tools.py`, add it to the `TOOLS` registry and to `ToolName` in `schemas.py`.
The planner prompt is built from the registry, so it learns about the tool automatically.

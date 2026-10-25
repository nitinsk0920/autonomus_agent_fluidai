# Submission Notes (video script helper)

## 1. Live demo (3-4 min)
1. Start the server: `uvicorn app.main:app --port 8000`
2. Run `python demo.py standard`, then `python demo.py complex`.
3. For each test, point at: agent-generated task list (with statuses), assumptions, conflicts + resolutions,
   reflection verdict, and then open `outputs/demo_<name>.docx`.
4. Optionally show http://127.0.0.1:8000/docs (Swagger) and a 422 for a too-short request.

Test inputs
* Standard: "Create a project plan for launching a customer support chatbot for a retail company over 3 months."
* Complex: board cloud-migration request with tiny budget + 1 month + full security/compliance + unknown format.
  Shows: the agent picks the document type itself, lists assumptions, and writes a resolution per conflict
  (phased rollout, reduced scope) that the document actually follows.

## 2. What I built (2-3 min)
* FastAPI `POST /agent` -> pipeline in `agent.py`: validate -> plan -> execute -> summarise -> reflect -> build docx -> respond.
* No agent framework: a plain Python loop. Planner (`planner.py`) asks Groq (Llama 3.3 70B, free tier) for a JSON plan
  validated by Pydantic; invalid plan -> error fed back to the LLM, retried once.
* Tools (`tools.py`) share one signature and live in a registry; the planner prompt is generated from it:
  `get_mock_data` (deterministic), `write_section` (LLM), `build_table` (LLM).
* `llm.py` is the single gateway: JSON mode, fence stripping, retry honouring Retry-After, fallback to Llama 3.1 8B.
* `docbuilder.py`: python-docx title block, summary, assumptions box, numbered sections, styled tables, header, page-number footer.
* Failed tasks are recorded (`status: failed`) and the run continues; `completed_with_errors` is reported honestly.

## The mandatory improvement: Reflection / self-check
* What: a reviewer LLM compares the draft to the original request and the agent's own plan, returns up to 3 issues;
  only the flagged sections are rewritten (or a missing one added), once. The executive summary is regenerated
  if anything changed, so it never contradicts the repaired body.
* Why: sections are written one at a time, so no single call sees the whole document. Ambiguous/conflicting
  requests are where drafts drift, and a review pass sees everything together.
* Safety: if the reviewer fails, the request still completes (`verdict: skipped`).

## 3. Debugging insight (1-2 min)  -- pick the one you actually hit
Candidate grounded in this code: small LLMs return sloppy JSON (markdown fences, `rows` as dicts, tool names with odd
casing, `"none"` instead of null). Root cause: trusting raw model output. Fix: `parse_json` tolerates fences/chatter,
and lenient Pydantic validators coerce shapes, with a unit test (`test_plan_accepts_sloppy_llm_values`).
Replace with your own real story if different.

## 4. Tradeoff (1-2 min)
Autonomous planning vs deterministic workflow: the LLM chooses doc type and tasks (flexible, handles ambiguous requests)
but is less predictable, so I constrained it: fixed tool registry, schema-validated plan, 2-10 task limit, retry with
feedback, and never-fatal task failures. Also mention: plain loop vs LangGraph (simplicity now, extensible later via the registry).

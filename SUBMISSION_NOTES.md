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

## 3. Debugging insight (1-2 min)  -- real story from testing
Issue: on the complex request the agent's own reviewer "fixed" the document, yet the budget table summed to $96,300
while the text said $91,300, and a 13-week mock timeline contradicted the 4-week assumption ("week 12" in the KPIs).
Root cause: two things. (1) `get_mock_data` returned a generic template that ignored the plan's constraints.
(2) An LLM reviewer can spot an inconsistency but cannot be trusted to do the arithmetic when rewriting.
Fix: the plan now carries `timeline_weeks` and `budget_usd`; mock data is scaled to them, every prompt gets a
"fixed figures" block, and `consistency.py` rescales a generated table's cost column in code (plus a Total row).
Result on re-run: costs sum to exactly $20,000 and every section says 4 weeks. Unit tests reproduce the original failure.
Second, shorter story (optional): Groq retired the default Llama models, every call 404'd; found via the error text +
Groq's deprecation page; defaults changed and a 404 now skips straight to the fallback model.

## 4. Tradeoff (1-2 min)
Autonomous planning vs deterministic workflow: the LLM chooses doc type and tasks (flexible, handles ambiguous requests)
but is less predictable, so I constrained it: fixed tool registry, schema-validated plan, 2-14 task limit, retry with
feedback, and never-fatal task failures. Also mention: plain loop vs LangGraph (simplicity now, extensible later via the registry).

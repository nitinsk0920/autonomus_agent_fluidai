"""FastAPI app: POST /agent (run the agent), GET /download/{id} (get the .docx), GET /health."""
import logging
import re
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import config
from app.agent import run_agent
from app.errors import AgentError, LLMConfigError
from app.schemas import AgentRequest, AgentResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(
    title="Autonomous Document Agent",
    version="1.0.0",
    description="Send a plain-English request. The agent plans its own tasks, executes them, "
    "self-reviews, and returns a Word document.",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/agent", response_model=AgentResponse)
def agent_endpoint(body: AgentRequest):
    """Input is validated by AgentRequest (10-2000 chars) before the agent starts."""
    request_id = uuid4().hex
    try:
        return run_agent(body.request, request_id)
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/download/{request_id}")
def download(request_id: str):
    # Only 32-char hex ids are accepted, so no path tricks are possible.
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise HTTPException(status_code=404, detail="Document not found")
    matches = list(config.OUTPUT_DIR.glob(f"*-{request_id}.docx"))
    if not matches:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(matches[0], media_type=DOCX_MIME, filename=matches[0].name)

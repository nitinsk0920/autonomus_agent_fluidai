"""Groq LLM client with JSON parsing, retry and model fallback.

Every part of the agent talks to the model through `chat_json()`, so all the
reliability logic lives in this one place.
"""
import json
import logging
import re
import time

from groq import Groq

from app import config
from app.errors import LLMConfigError, LLMError

log = logging.getLogger("agent.llm")

ATTEMPTS_PER_MODEL = 2
MAX_WAIT_SECONDS = 20
_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY or config.GROQ_API_KEY.startswith("your_"):
            raise LLMConfigError("GROQ_API_KEY is missing. Add your key to the .env file and restart.")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _call(model: str, system: str, user: str, max_tokens: int) -> str:
    """One raw Groq call in JSON mode."""
    extra = {}
    if model.startswith("openai/gpt-oss"):
        # Reasoning models spend max_tokens on thinking too; keep it short so the JSON isn't cut off.
        extra["extra_body"] = {"reasoning_effort": "low"}
    response = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        **extra,
    )
    return response.choices[0].message.content or ""


def parse_json(raw: str) -> dict:
    """Turn a model reply into a dict, tolerating markdown fences and extra chatter."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object found in the model reply")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Model reply was JSON but not an object")
    return data


def _wait_time(exc: Exception, attempt: int) -> float:
    """Honour Groq's Retry-After header on rate limits, otherwise back off 2s, 4s..."""
    response = getattr(exc, "response", None)
    retry_after = getattr(response, "headers", {}).get("retry-after") if response is not None else None
    try:
        return min(float(retry_after) + 0.5, MAX_WAIT_SECONDS)
    except (TypeError, ValueError):
        return 2.0 * attempt


def chat_json(system: str, user: str, *, max_tokens: int = 1500, label: str = "llm") -> dict:
    """Ask the LLM for a JSON object. Retries, then falls back to a smaller model."""
    models = list(dict.fromkeys([config.PRIMARY_MODEL, config.FALLBACK_MODEL]))
    last_error = None
    for model in models:
        for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
            try:
                return parse_json(_call(model, system, user, max_tokens))
            except LLMConfigError:
                raise  # no point retrying a missing key
            except Exception as exc:  # rate limit, bad JSON, network blip...
                last_error = exc
                if getattr(exc, "status_code", None) in (400, 401, 403, 404):
                    log.warning("[%s] %s is not usable (%s). Skipping to the next model.", label, model, exc)
                    break  # retrying the same model cannot help (e.g. retired model id)
                wait = _wait_time(exc, attempt)
                log.warning("[%s] %s attempt %d failed (%s). Waiting %.1fs", label, model, attempt, exc, wait)
                time.sleep(wait)
    raise LLMError(f"[{label}] LLM failed after retries and fallback: {last_error}")

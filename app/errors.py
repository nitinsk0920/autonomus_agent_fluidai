"""Small exception hierarchy so the API layer can map failures to clean HTTP errors."""


class AgentError(Exception):
    """Base class for every agent failure."""


class LLMError(AgentError):
    """The LLM could not give a usable answer, even after retries and the fallback model."""


class LLMConfigError(LLMError):
    """Configuration problem (e.g. missing API key). Retrying cannot help."""


class PlanningError(AgentError):
    """The planner could not produce a valid plan."""

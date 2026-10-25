"""Central configuration. Values come from the .env file in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# Groq retired llama-3.3-70b-versatile / llama-3.1-8b-instant on 2026-08-16 (free tier).
PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b").strip()

# Generated Word files are saved here.
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "outputs")

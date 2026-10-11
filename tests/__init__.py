"""Tests must be hermetic: pin config before jobagent is imported so a developer's .env (Ollama, Gmail, live
DRY_RUN) can never leak in. load_env() never overrides variables that are already set."""
import os

os.environ["JOBAGENT_LLM"] = "0"
os.environ["DRY_RUN"] = "1"
os.environ["JOBAGENT_PDF"] = "0"      # no browser launches in unit tests
for k in ("ANTHROPIC_API_KEY", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
    os.environ[k] = ""

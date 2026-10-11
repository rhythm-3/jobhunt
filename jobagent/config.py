from __future__ import annotations

import os
from dataclasses import dataclass, field

from .env import load_env

load_env()   # .env (chmod 600) feeds the defaults below; real env vars win


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("JOBAGENT_DB", "jobagent.db")
    out_dir: str = os.getenv("JOBAGENT_OUT", "out")
    match_threshold: float = float(os.getenv("MATCH_THRESHOLD", "0.30"))
    require_approval: bool = True       # HITL gate; cannot be disabled via env on purpose
    dry_run: bool = os.getenv("DRY_RUN", "1") == "1"   # default: never really send
    max_applications_per_day: int = int(os.getenv("MAX_APPS_PER_DAY", "20"))
    max_emails_per_hour: int = int(os.getenv("MAX_EMAILS_PER_HOUR", "5"))
    max_attempts: int = 3
    webhook_url: str | None = os.getenv("NOTIFY_WEBHOOK_URL")
    signing_secret: str = os.getenv("SIGNING_SECRET", "dev-only-change-me")   # source from Vault in prod
    public_url: str = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000")
    api_token: str | None = os.getenv("DASHBOARD_TOKEN")
    poll_inbox: bool = os.getenv("INBOX_POLL", "0") == "1"        # needs a gmail.readonly refresh token
    poll_interval_s: int = int(os.getenv("INBOX_POLL_SECONDS", "300"))
    llm_model: str = os.getenv("JOBAGENT_MODEL", "claude-opus-5-5")
    # JOBAGENT_LLM: "ollama" (free, local) | "claude" (or "1") | "0" (rule-based only). Unset = claude if a key exists.
    llm_provider: str = {"1": "claude", "true": "claude"}.get(
        os.getenv("JOBAGENT_LLM", "claude" if os.getenv("ANTHROPIC_API_KEY") else "0").lower(),
        os.getenv("JOBAGENT_LLM", "0").lower())
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    @property
    def use_llm(self) -> bool:
        return self.llm_provider in ("claude", "ollama")

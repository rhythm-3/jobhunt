"""Secret access seam. Dev reads env vars; prod swaps in Vault / AWS Secrets Manager with the same interface."""
from __future__ import annotations

import os
from typing import Protocol


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvSecrets:
    def get(self, name: str) -> str | None:
        return os.getenv(name) or None

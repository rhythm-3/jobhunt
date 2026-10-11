"""Minimal .env loader (no dependency). Never overrides variables already set in the real environment."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    import sys
    if path is None and "unittest" in sys.modules and os.getenv("JOBAGENT_DOTENV_IN_TESTS") != "1":
        return          # tests must never see real credentials or a live model, whatever the import order
    p = path or Path(__file__).resolve().parent.parent / ".env"
    if not p.is_file():
        return
    if p.stat().st_mode & 0o077:
        raise PermissionError(f"{p} is readable by other users; run: chmod 600 {p}")
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def update_env(values: dict[str, str | None], path: Path | None = None) -> None:
    """Set (or with None, remove) keys in .env atomically, keeping it owner-only, and mirror into os.environ."""
    p = path or Path(__file__).resolve().parent.parent / ".env"
    lines = p.read_text().splitlines() if p.is_file() else []
    keep = [l for l in lines if l.partition("=")[0].strip() not in values]
    keep += [f"{k}={v}" for k, v in values.items() if v is not None]
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(keep) + "\n")
    os.replace(tmp, p)
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

"""Lightweight NLP used as the deterministic baseline (swap embed() for a real model in prod)."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

STOP = set("a an and are as at be by for from has have in is it of on or our that the to we will with you your "
           "this who their they them can not but also etc experience years work team role job "
           "requirements requirement such including strong ability knowledge understanding familiarity proficiency "
           "excellent preferred nice plus bonus responsibilities qualifications skills working using used use "
           "well new like more other multiple various within across into over".split())
TECH = {"python", "go", "golang", "rust", "java", "kotlin", "typescript", "javascript", "react", "node", "fastapi",
        "django", "flask", "postgres", "postgresql", "redis", "kafka", "rabbitmq", "docker", "kubernetes", "k8s",
        "aws", "gcp", "azure", "terraform", "sql", "graphql", "rest", "grpc", "pytorch", "llm", "rag", "langchain",
        "langgraph", "playwright", "ci/cd", "opentelemetry", "celery", "pgvector", "airflow", "spark", "dbt",
        "splunk", "sigma", "yara", "kql", "spl", "torq", "wiz", "xsoar", "soar", "siem", "edr", "bitbucket", "virustotal",
        "opensearch", "bedrock", "datadog", "jira", "crowdstrike", "sentinel", "qradar", "elastic", "okta", "snowflake",
        "github", "gitlab", "jenkins", "ansible", "ebpf", "zeek", "suricata", "sumo", "chronicle", "defender"}
ALIASES = {"postgresql": "postgres", "golang": "go", "k8s": "kubernetes"}


def tokens(s: str) -> list[str]:
    # strip sentence punctuation that the pattern allows inside a term ("node.js", "ci/cd"): "jenkins." must equal "jenkins"
    toks = (t.rstrip("./-") for t in re.findall(r"[a-z][a-z0-9+#./-]*", s.lower()))
    return [ALIASES.get(t, t) for t in toks if t not in STOP and len(t) > 1]


def extract_keywords(s: str, top: int = 25) -> list[str]:
    toks = tokens(s)
    tech = [t for t in dict.fromkeys(toks) if t in TECH]
    freq = Counter(t for t in toks if t not in TECH and len(t) > 3)
    return (tech + [w for w, _ in freq.most_common(top)])[:top]


def embed(s: str, dim: int = 256) -> list[float]:
    """Hashing-trick bag-of-words vector. Deterministic, dependency-free."""
    v = [0.0] * dim
    for t in tokens(s):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def fingerprint(title: str, company: str, location: str = "") -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return hashlib.sha1(f"{norm(company)}|{norm(title)}|{norm(location)}".encode()).hexdigest()[:16]

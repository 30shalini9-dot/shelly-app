from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(env_name: str, default: str) -> Path:
    value = Path(os.getenv(env_name, default))
    return value if value.is_absolute() else BACKEND_DIR / value


DATABASE_PATH = _resolve_path("SHELDON_DATABASE_PATH", "data/sheldon.db")
UPLOAD_DIR = _resolve_path("SHELDON_UPLOAD_DIR", "data/uploads")
AI_VISION_RUN_DIR = _resolve_path("SHELDON_AI_VISION_RUN_DIR", "data/ai_vision")
AGENT_JOB_RUN_DIR = _resolve_path("SHELDON_AGENT_JOB_RUN_DIR", "data/agent_jobs")
SEED_DATA = os.getenv("SHELDON_SEED_DATA", "true").lower() in {"1", "true", "yes"}
AI_VISION_DUMMY_FULL_MARKS = os.getenv(
    "SHELDON_AI_VISION_DUMMY_FULL_MARKS",
    "true",
).lower() in {"1", "true", "yes"}
CORNERSTONE_API_URL = os.getenv(
    "SHELDON_CORNERSTONE_API_URL",
    "http://localhost:8001",
).rstrip("/")
PUBLIC_API_URL = os.getenv(
    "SHELDON_PUBLIC_API_URL",
    "http://localhost:8000",
).rstrip("/")
CORNERSTONE_WEBHOOK_SECRET = os.getenv(
    "SHELDON_CORNERSTONE_WEBHOOK_SECRET",
    "sheldon-local-agent",
)
AGENT_DUMMY_FULL_MARKS = os.getenv(
    "SHELDON_AGENT_DUMMY_FULL_MARKS",
    "true",
).lower() in {"1", "true", "yes"}
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "SHELDON_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

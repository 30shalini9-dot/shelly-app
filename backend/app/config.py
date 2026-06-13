from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(env_name: str, default: str) -> Path:
    value = Path(os.getenv(env_name, default))
    return value if value.is_absolute() else BACKEND_DIR / value


DATABASE_PATH = _resolve_path("SHELDON_DATABASE_PATH", "data/sheldon.db")
UPLOAD_DIR = _resolve_path("SHELDON_UPLOAD_DIR", "data/uploads")
SEED_DATA = os.getenv("SHELDON_SEED_DATA", "true").lower() in {"1", "true", "yes"}
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "SHELDON_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

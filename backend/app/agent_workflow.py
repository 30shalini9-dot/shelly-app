from __future__ import annotations

import hmac
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx


def submit_cornerstone_job(
    *,
    base_url: str,
    pages: list[dict[str, Any]],
    webhook_url: str,
    webhook_secret: str,
) -> dict[str, Any]:
    with ExitStack() as stack:
        files = [
            (
                "images",
                (
                    page["original_filename"],
                    stack.enter_context(Path(page["stored_path"]).open("rb")),
                    page["content_type"],
                ),
            )
            for page in pages
        ]
        response = httpx.post(
            f"{base_url}/v1/jobs",
            data={
                "webhook_url": webhook_url,
                "webhook_secret": webhook_secret,
                "coordinate_space": "enhanced",
                "image_delivery": "url",
                "ocr_enabled": "true",
            },
            files=files,
            timeout=60,
        )
    response.raise_for_status()
    return response.json()


def fetch_agent_image(url: str) -> tuple[bytes, str]:
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "image/png")


def fetch_cornerstone_status(
    *,
    base_url: str,
    job_id: str,
    status_url: str | None = None,
) -> dict[str, Any]:
    url = status_url or f"{base_url}/v1/jobs/{job_id}"
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def valid_cornerstone_signature(
    body: bytes,
    supplied_signature: str,
    secret: str,
) -> bool:
    expected = f"sha256={hmac.new(secret.encode(), body, sha256).hexdigest()}"
    return hmac.compare_digest(expected, supplied_signature)

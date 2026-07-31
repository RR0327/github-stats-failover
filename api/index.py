from __future__ import annotations

import logging
from pathlib import Path

from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import Response

from services.failover import (
    CardType,
    FailoverService,
    Settings,
    SourceMode,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(
    dotenv_path=ENV_FILE,
    override=False,
)

settings = Settings.from_environment()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

service = FailoverService(settings)

app = FastAPI(
    title="GitHub Stats Failover",
    version="3.0.0",
    description=(
        "Always returns a GitHub card through primary, live Python backup, "
        "repository snapshot, and permanent safety-card layers."
    ),
)


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": "GitHub Stats Failover",
        "status": "running",
        "github_username": settings.github_username,
        "failover_order": [
            "primary",
            "python-backup",
            "repository-snapshot",
            "permanent-safety-card",
        ],
        "supported_types": [
            "stats",
            "streak",
            "languages",
        ],
        "example": "/api/github-card?type=stats&source=auto",
        "documentation": "/docs",
    }


@app.get("/health")
async def health() -> dict[str, object]:
    snapshots = {
        card_type: service.snapshot_path(card_type).exists()
        for card_type in ("stats", "streak", "languages")
    }

    return {
        "status": "healthy",
        "service": "github-stats-failover",
        "snapshots": snapshots,
    }


@app.get(
    "/api/github-card",
    response_class=Response,
    responses={
        200: {
            "description": "A GitHub statistics image card.",
            "content": {
                "image/svg+xml": {},
                "image/png": {},
                "image/jpeg": {},
                "image/webp": {},
            },
        }
    },
)
async def github_card(
    card_type: CardType = Query(alias="type"),
    source: SourceMode = Query(default="auto"),
) -> Response:
    """
    source=auto:
        primary -> Python backup -> saved snapshot -> safety card

    source=primary:
        primary -> saved snapshot -> safety card

    source=backup:
        Python backup -> saved snapshot -> safety card

    source=snapshot:
        saved snapshot -> safety card
    """
    result = await service.get_card(card_type, source)
    cache_control = service.cache_control_for(result.source)

    return Response(
        content=result.body,
        media_type=result.content_type,
        headers={
            "Cache-Control": cache_control,
            "CDN-Cache-Control": cache_control,
            "X-Failover-Source": result.source,
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
        },
    )

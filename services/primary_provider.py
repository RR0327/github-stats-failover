from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

CardType = Literal["stats", "streak", "languages"]


@dataclass(frozen=True)
class ImageCard:
    body: bytes
    content_type: str


class PrimaryProvider:
    """Fetches and validates the normal third-party README cards."""

    ERROR_MARKERS = (
        "something went wrong",
        "maximum retries exceeded",
        "rate limit exceeded",
        "upstream request timeout",
        "service unavailable",
        "temporarily unavailable",
        "please try again later",
        "error fetching",
        "could not fetch",
        "request failed",
        "internal server error",
    )

    def __init__(
        self,
        *,
        username: str,
        stats_url_template: str,
        streak_url_template: str,
        languages_url_template: str,
        timeout_seconds: float,
        max_image_bytes: int,
        user_agent: str,
    ) -> None:
        self.username = username
        self.url_templates: dict[CardType, str] = {
            "stats": stats_url_template,
            "streak": streak_url_template,
            "languages": languages_url_template,
        }
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes
        self.user_agent = user_agent

    def url_for(self, card_type: CardType) -> str:
        encoded_username = quote(self.username, safe="")
        return self.url_templates[card_type].replace(
            "{username}",
            encoded_username,
        )

    @staticmethod
    def _is_image(content_type: str) -> bool:
        normalized = content_type.lower()
        return normalized.startswith("image/") or "svg" in normalized

    def _contains_error_card(
        self,
        body: bytes,
        content_type: str,
    ) -> bool:
        if "svg" not in content_type.lower():
            return False

        text = body.decode("utf-8", errors="ignore").lower()
        return any(marker in text for marker in self.ERROR_MARKERS)

    async def fetch(self, card_type: CardType) -> ImageCard | None:
        timeout = httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=min(self.timeout_seconds, 5.0),
        )

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "Accept": "image/svg+xml,image/*;q=0.9,*/*;q=0.1",
                    "User-Agent": self.user_agent,
                },
            ) as client:
                async with client.stream(
                    "GET",
                    self.url_for(card_type),
                ) as response:
                    if response.status_code != 200:
                        return None

                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";")[0]
                        .strip()
                    )
                    if not self._is_image(content_type):
                        return None

                    chunks: list[bytes] = []
                    total_size = 0

                    async for chunk in response.aiter_bytes():
                        total_size += len(chunk)
                        if total_size > self.max_image_bytes:
                            return None
                        chunks.append(chunk)

        except (httpx.TimeoutException, httpx.HTTPError):
            return None

        body = b"".join(chunks)

        if len(body) < 200:
            return None

        if self._contains_error_card(body, content_type):
            return None

        return ImageCard(
            body=body,
            content_type=content_type or "image/svg+xml",
        )

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from services.github_api import GitHubApiClient
from services.primary_provider import ImageCard, PrimaryProvider
from services.svg_generator import (
    render_languages_card,
    render_permanent_safety_card,
    render_stats_card,
    render_streak_card,
)

CardType = Literal["stats", "streak", "languages"]
SourceMode = Literal["auto", "primary", "backup", "snapshot"]


class ConfigurationError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


def _required_text(name: str, *, allow_empty: bool = False) -> str:
    if name not in os.environ:
        raise ConfigurationError(
            f"Missing required environment variable: {name}"
        )

    value = os.environ[name].strip()
    if not allow_empty and not value:
        raise ConfigurationError(
            f"Environment variable {name} cannot be empty."
        )
    return value


def _positive_int(name: str) -> int:
    raw_value = _required_text(name)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be an integer."
        ) from exc

    if value <= 0:
        raise ConfigurationError(
            f"Environment variable {name} must be greater than zero."
        )
    return value


def _positive_float(name: str) -> float:
    raw_value = _required_text(name)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be a number."
        ) from exc

    if value <= 0:
        raise ConfigurationError(
            f"Environment variable {name} must be greater than zero."
        )
    return value


def _boolean(name: str) -> bool:
    value = _required_text(name).lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ConfigurationError(
        f"Environment variable {name} must be true or false."
    )


@dataclass(frozen=True)
class Settings:
    github_username: str
    github_token: str
    github_api_base_url: str
    github_api_version: str
    github_contributions_url: str
    github_timezone: str

    primary_stats_url: str
    primary_streak_url: str
    primary_languages_url: str

    primary_timeout_seconds: float
    backup_timeout_seconds: float
    max_image_bytes: int
    max_repositories: int
    language_concurrency: int
    include_forks: bool
    streak_lookback_days: int
    live_data_cache_seconds: int

    success_cache_seconds: int
    snapshot_cache_seconds: int
    stale_while_revalidate_seconds: int

    fallback_directory: Path
    user_agent: str
    log_level: str

    @classmethod
    def from_environment(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[1]
        fallback_value = _required_text("FALLBACK_DIRECTORY")
        fallback_directory = Path(fallback_value)

        if not fallback_directory.is_absolute():
            fallback_directory = project_root / fallback_directory

        return cls(
            github_username=_required_text("GITHUB_USERNAME"),
            github_token=_required_text(
                "GITHUB_TOKEN",
                allow_empty=True,
            ),
            github_api_base_url=_required_text(
                "GITHUB_API_BASE_URL"
            ),
            github_api_version=_required_text(
                "GITHUB_API_VERSION"
            ),
            github_contributions_url=_required_text(
                "GITHUB_CONTRIBUTIONS_URL"
            ),
            github_timezone=_required_text("GITHUB_TIMEZONE"),
            primary_stats_url=_required_text(
                "PRIMARY_STATS_URL"
            ),
            primary_streak_url=_required_text(
                "PRIMARY_STREAK_URL"
            ),
            primary_languages_url=_required_text(
                "PRIMARY_LANGUAGES_URL"
            ),
            primary_timeout_seconds=_positive_float(
                "PRIMARY_TIMEOUT_SECONDS"
            ),
            backup_timeout_seconds=_positive_float(
                "BACKUP_TIMEOUT_SECONDS"
            ),
            max_image_bytes=_positive_int("MAX_IMAGE_BYTES"),
            max_repositories=_positive_int("MAX_REPOSITORIES"),
            language_concurrency=_positive_int(
                "LANGUAGE_CONCURRENCY"
            ),
            include_forks=_boolean("INCLUDE_FORKS"),
            streak_lookback_days=_positive_int(
                "STREAK_LOOKBACK_DAYS"
            ),
            live_data_cache_seconds=_positive_int(
                "LIVE_DATA_CACHE_SECONDS"
            ),
            success_cache_seconds=_positive_int(
                "SUCCESS_CACHE_SECONDS"
            ),
            snapshot_cache_seconds=_positive_int(
                "SNAPSHOT_CACHE_SECONDS"
            ),
            stale_while_revalidate_seconds=_positive_int(
                "STALE_WHILE_REVALIDATE_SECONDS"
            ),
            fallback_directory=fallback_directory,
            user_agent=_required_text("USER_AGENT"),
            log_level=_required_text("LOG_LEVEL").upper(),
        )


@dataclass(frozen=True)
class FailoverResult:
    body: bytes
    content_type: str
    source: str


class FailoverService:
    """
    Complete failover chain:

    primary third-party card -> Python live backup -> repository SVG snapshot
    -> permanent generated safety card.
    """

    TITLES: dict[CardType, str] = {
        "stats": "GitHub Statistics",
        "streak": "GitHub Contribution Streak",
        "languages": "Most Used Languages",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("github-stats-failover")

        self.primary_provider = PrimaryProvider(
            username=settings.github_username,
            stats_url_template=settings.primary_stats_url,
            streak_url_template=settings.primary_streak_url,
            languages_url_template=settings.primary_languages_url,
            timeout_seconds=settings.primary_timeout_seconds,
            max_image_bytes=settings.max_image_bytes,
            user_agent=settings.user_agent,
        )

        self.github = GitHubApiClient(
            username=settings.github_username,
            token=settings.github_token,
            api_base_url=settings.github_api_base_url,
            api_version=settings.github_api_version,
            contributions_url_template=(
                settings.github_contributions_url
            ),
            timezone_name=settings.github_timezone,
            timeout_seconds=settings.backup_timeout_seconds,
            max_repositories=settings.max_repositories,
            language_concurrency=settings.language_concurrency,
            include_forks=settings.include_forks,
            streak_lookback_days=settings.streak_lookback_days,
            live_data_cache_seconds=(
                settings.live_data_cache_seconds
            ),
            user_agent=settings.user_agent,
        )

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.settings.github_timezone))

    async def generate_live_backup(
        self,
        card_type: CardType,
    ) -> ImageCard:
        updated_at = self._now()

        if card_type == "stats":
            summary = await self.github.fetch_profile_summary()
            body = render_stats_card(
                summary,
                updated_at=updated_at,
            )

        elif card_type == "languages":
            summary = await self.github.fetch_language_summary()
            body = render_languages_card(
                summary,
                username=self.settings.github_username,
                updated_at=updated_at,
            )

        else:
            summary = await self.github.fetch_streak_summary()
            body = render_streak_card(
                summary,
                username=self.settings.github_username,
                updated_at=updated_at,
            )

        return ImageCard(
            body=body,
            content_type="image/svg+xml",
        )

    def snapshot_path(self, card_type: CardType) -> Path:
        return self.settings.fallback_directory / f"{card_type}.svg"

    def load_snapshot(self, card_type: CardType) -> ImageCard | None:
        path = self.snapshot_path(card_type)

        try:
            body = path.read_bytes()
        except OSError:
            return None

        if len(body) < 200:
            return None

        if b"<svg" not in body[:500].lower():
            return None

        return ImageCard(
            body=body,
            content_type="image/svg+xml",
        )

    def permanent_safety_card(
        self,
        card_type: CardType,
    ) -> ImageCard:
        body = render_permanent_safety_card(
            card_title=self.TITLES[card_type],
            username=self.settings.github_username,
            message=(
                "The latest bundled profile card remains available."
            ),
        )
        return ImageCard(
            body=body,
            content_type="image/svg+xml",
        )

    async def get_card(
        self,
        card_type: CardType,
        source_mode: SourceMode,
    ) -> FailoverResult:
        if source_mode in {"auto", "primary"}:
            primary = await self.primary_provider.fetch(card_type)
            if primary is not None:
                return FailoverResult(
                    body=primary.body,
                    content_type=primary.content_type,
                    source="primary",
                )

            self.logger.warning(
                "Primary card failed for %s",
                card_type,
            )

        if source_mode in {"auto", "backup"}:
            try:
                backup = await self.generate_live_backup(card_type)
            except Exception as exc:
                self.logger.warning(
                    "Live Python backup failed for %s: %s",
                    card_type,
                    exc,
                )
            else:
                return FailoverResult(
                    body=backup.body,
                    content_type=backup.content_type,
                    source="python-backup",
                )

        snapshot = self.load_snapshot(card_type)
        if snapshot is not None:
            return FailoverResult(
                body=snapshot.body,
                content_type=snapshot.content_type,
                source="repository-snapshot",
            )

        safety = self.permanent_safety_card(card_type)
        return FailoverResult(
            body=safety.body,
            content_type=safety.content_type,
            source="permanent-safety-card",
        )

    def cache_control_for(self, source: str) -> str:
        cache_seconds = (
            self.settings.snapshot_cache_seconds
            if source in {
                "repository-snapshot",
                "permanent-safety-card",
            }
            else self.settings.success_cache_seconds
        )

        return (
            f"public, max-age=60, s-maxage={cache_seconds}, "
            f"stale-while-revalidate="
            f"{self.settings.stale_while_revalidate_seconds}"
        )

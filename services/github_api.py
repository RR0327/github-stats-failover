from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup


class GitHubDataError(RuntimeError):
    """Raised when live GitHub data cannot be collected or parsed."""


@dataclass(frozen=True)
class ProfileSummary:
    login: str
    name: str
    public_repositories: int
    followers: int
    following: int
    public_gists: int
    total_stars: int
    total_forks: int


@dataclass(frozen=True)
class LanguageItem:
    name: str
    bytes_used: int
    percentage: float


@dataclass(frozen=True)
class LanguageSummary:
    items: tuple[LanguageItem, ...]
    total_bytes: int
    repositories_scanned: int


@dataclass(frozen=True)
class ContributionDay:
    day: date
    count: int


@dataclass(frozen=True)
class StreakSummary:
    total_contributions: int
    current_streak: int
    longest_streak: int
    active_days: int
    period_start: date
    period_end: date


class GitHubApiClient:
    """
    Collects the live data used by the Python-generated backup cards.

    Public information works without a token. Adding GITHUB_TOKEN increases
    the REST API rate limit and may expose additional data permitted by that
    token.
    """

    def __init__(
        self,
        *,
        username: str,
        token: str,
        api_base_url: str,
        api_version: str,
        contributions_url_template: str,
        timezone_name: str,
        timeout_seconds: float,
        max_repositories: int,
        language_concurrency: int,
        include_forks: bool,
        streak_lookback_days: int,
        live_data_cache_seconds: int,
        user_agent: str,
    ) -> None:
        self.username = username
        self.token = token.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.api_version = api_version
        self.contributions_url_template = contributions_url_template
        self.timezone = ZoneInfo(timezone_name)
        self.timeout_seconds = timeout_seconds
        self.max_repositories = max_repositories
        self.language_concurrency = language_concurrency
        self.include_forks = include_forks
        self.streak_lookback_days = streak_lookback_days
        self.live_data_cache_seconds = live_data_cache_seconds
        self.user_agent = user_agent

        self._cache: dict[str, tuple[float, Any]] = {}

    def _headers(self, *, authenticated: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": self.user_agent,
        }
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _cache_get(self, key: str) -> Any | None:
        cached = self._cache.get(key)
        if cached is None:
            return None

        created_at, value = cached
        if time.monotonic() - created_at > self.live_data_cache_seconds:
            self._cache.pop(key, None)
            return None

        return value

    def _cache_set(self, key: str, value: Any) -> Any:
        self._cache[key] = (time.monotonic(), value)
        return value

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> Any:
        response = await client.get(url, headers=self._headers())

        # An installation token may not have access to every public repository.
        # Retry the same public request without authorization before failing.
        if (
            self.token
            and response.status_code in {401, 403, 404}
        ):
            response = await client.get(
                url,
                headers=self._headers(authenticated=False),
            )

        if response.status_code != 200:
            raise GitHubDataError(
                f"GitHub API returned HTTP {response.status_code} for {url}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GitHubDataError(
                f"GitHub API returned invalid JSON for {url}"
            ) from exc

    async def _request_text(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> str:
        response = await client.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self.user_agent,
            },
        )

        if response.status_code != 200:
            raise GitHubDataError(
                f"GitHub returned HTTP {response.status_code} for {url}"
            )

        if len(response.content) < 200:
            raise GitHubDataError(
                "GitHub contribution page returned an empty response."
            )

        return response.text

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=min(self.timeout_seconds, 5.0),
        )
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    async def fetch_profile(self) -> dict[str, Any]:
        cached = self._cache_get("profile")
        if cached is not None:
            return cached

        url = f"{self.api_base_url}/users/{quote(self.username, safe='')}"

        async with self._client() as client:
            payload = await self._request_json(client, url)

        if not isinstance(payload, dict):
            raise GitHubDataError("GitHub profile response was not an object.")

        return self._cache_set("profile", payload)

    async def fetch_repositories(self) -> list[dict[str, Any]]:
        cached = self._cache_get("repositories")
        if cached is not None:
            return cached

        repositories: list[dict[str, Any]] = []
        page = 1

        async with self._client() as client:
            while len(repositories) < self.max_repositories:
                remaining = self.max_repositories - len(repositories)
                per_page = min(100, remaining)

                url = (
                    f"{self.api_base_url}/users/"
                    f"{quote(self.username, safe='')}/repos"
                    f"?type=owner&sort=updated&direction=desc"
                    f"&per_page={per_page}&page={page}"
                )

                payload = await self._request_json(client, url)

                if not isinstance(payload, list):
                    raise GitHubDataError(
                        "GitHub repositories response was not a list."
                    )

                if not payload:
                    break

                for repository in payload:
                    if not isinstance(repository, dict):
                        continue
                    if not self.include_forks and repository.get("fork"):
                        continue
                    repositories.append(repository)
                    if len(repositories) >= self.max_repositories:
                        break

                if len(payload) < per_page:
                    break

                page += 1

        return self._cache_set("repositories", repositories)

    async def fetch_profile_summary(self) -> ProfileSummary:
        profile, repositories = await asyncio.gather(
            self.fetch_profile(),
            self.fetch_repositories(),
        )

        total_stars = sum(
            int(repository.get("stargazers_count") or 0)
            for repository in repositories
        )
        total_forks = sum(
            int(repository.get("forks_count") or 0)
            for repository in repositories
        )

        return ProfileSummary(
            login=str(profile.get("login") or self.username),
            name=str(profile.get("name") or self.username),
            public_repositories=int(profile.get("public_repos") or 0),
            followers=int(profile.get("followers") or 0),
            following=int(profile.get("following") or 0),
            public_gists=int(profile.get("public_gists") or 0),
            total_stars=total_stars,
            total_forks=total_forks,
        )

    async def fetch_language_summary(self) -> LanguageSummary:
        cached = self._cache_get("language_summary")
        if cached is not None:
            return cached

        repositories = await self.fetch_repositories()
        semaphore = asyncio.Semaphore(self.language_concurrency)
        totals: dict[str, int] = {}

        async def fetch_one(repository: dict[str, Any]) -> dict[str, int]:
            full_name = str(repository.get("full_name") or "")
            if not full_name:
                return {}

            url = (
                f"{self.api_base_url}/repos/"
                f"{quote(full_name, safe='/')}/languages"
            )

            async with semaphore:
                try:
                    async with self._client() as client:
                        payload = await self._request_json(client, url)
                except (GitHubDataError, httpx.HTTPError):
                    return {}

            if not isinstance(payload, dict):
                return {}

            cleaned: dict[str, int] = {}
            for language, byte_count in payload.items():
                try:
                    cleaned[str(language)] = int(byte_count)
                except (TypeError, ValueError):
                    continue
            return cleaned

        language_maps = await asyncio.gather(
            *(fetch_one(repository) for repository in repositories)
        )

        for language_map in language_maps:
            for language, byte_count in language_map.items():
                totals[language] = totals.get(language, 0) + byte_count

        # A lightweight fallback when individual language endpoints are limited.
        if not totals:
            for repository in repositories:
                language = repository.get("language")
                if not language:
                    continue
                repository_size = int(repository.get("size") or 1)
                totals[str(language)] = (
                    totals.get(str(language), 0) + max(repository_size, 1)
                )

        total_bytes = sum(totals.values())
        if total_bytes <= 0:
            raise GitHubDataError(
                "No language information was available for the repositories."
            )

        sorted_languages = sorted(
            totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        items = tuple(
            LanguageItem(
                name=language,
                bytes_used=byte_count,
                percentage=(byte_count / total_bytes) * 100,
            )
            for language, byte_count in sorted_languages
        )

        summary = LanguageSummary(
            items=items,
            total_bytes=total_bytes,
            repositories_scanned=len(repositories),
        )
        return self._cache_set("language_summary", summary)

    @staticmethod
    def _count_from_text(text: str) -> int | None:
        normalized = " ".join(text.split()).lower()

        if "no contributions" in normalized:
            return 0

        match = re.search(r"(\d[\d,]*)\s+contributions?", normalized)
        if match:
            return int(match.group(1).replace(",", ""))

        return None

    @classmethod
    def parse_contribution_days(cls, html: str) -> list[ContributionDay]:
        soup = BeautifulSoup(html, "html.parser")
        counts: dict[date, int] = {}

        for element in soup.select("[data-date]"):
            raw_date = str(element.get("data-date") or "").strip()
            try:
                contribution_date = date.fromisoformat(raw_date)
            except ValueError:
                continue

            raw_count = element.get("data-count")
            if raw_count is not None:
                try:
                    counts[contribution_date] = int(str(raw_count))
                    continue
                except ValueError:
                    pass

            candidate_texts: list[str] = []

            aria_label = element.get("aria-label")
            if aria_label:
                candidate_texts.append(str(aria_label))

            element_id = str(element.get("id") or "")
            if element_id:
                tooltip = soup.find(attrs={"for": element_id})
                if tooltip is not None:
                    candidate_texts.append(tooltip.get_text(" ", strip=True))

            candidate_texts.append(element.get_text(" ", strip=True))

            for candidate_text in candidate_texts:
                parsed_count = cls._count_from_text(candidate_text)
                if parsed_count is not None:
                    counts[contribution_date] = parsed_count
                    break

        # Compatibility fallback for markup containing data-date/data-count
        # attributes in an order BeautifulSoup did not associate as expected.
        if not counts:
            patterns = [
                re.compile(
                    r'data-date=["\'](\d{4}-\d{2}-\d{2})["\']'
                    r'[^>]*data-count=["\'](\d+)["\']',
                    re.IGNORECASE,
                ),
                re.compile(
                    r'data-count=["\'](\d+)["\']'
                    r'[^>]*data-date=["\'](\d{4}-\d{2}-\d{2})["\']',
                    re.IGNORECASE,
                ),
            ]

            for match in patterns[0].finditer(html):
                counts[date.fromisoformat(match.group(1))] = int(
                    match.group(2)
                )

            for match in patterns[1].finditer(html):
                counts[date.fromisoformat(match.group(2))] = int(
                    match.group(1)
                )

        if not counts:
            raise GitHubDataError(
                "The GitHub contribution calendar could not be parsed."
            )

        return [
            ContributionDay(day=day, count=count)
            for day, count in sorted(counts.items())
        ]

    @staticmethod
    def calculate_streak_summary(
        contribution_days: list[ContributionDay],
        *,
        period_start: date,
        period_end: date,
    ) -> StreakSummary:
        counts = {item.day: item.count for item in contribution_days}

        current = period_start
        ordered_counts: list[tuple[date, int]] = []
        while current <= period_end:
            ordered_counts.append((current, counts.get(current, 0)))
            current += timedelta(days=1)

        total_contributions = sum(count for _, count in ordered_counts)
        active_days = sum(1 for _, count in ordered_counts if count > 0)

        longest_streak = 0
        running_streak = 0
        for _, count in ordered_counts:
            if count > 0:
                running_streak += 1
                longest_streak = max(longest_streak, running_streak)
            else:
                running_streak = 0

        effective_end = period_end
        if counts.get(effective_end, 0) == 0:
            effective_end -= timedelta(days=1)

        current_streak = 0
        cursor = effective_end
        while cursor >= period_start and counts.get(cursor, 0) > 0:
            current_streak += 1
            cursor -= timedelta(days=1)

        return StreakSummary(
            total_contributions=total_contributions,
            current_streak=current_streak,
            longest_streak=longest_streak,
            active_days=active_days,
            period_start=period_start,
            period_end=period_end,
        )

    async def fetch_streak_summary(self) -> StreakSummary:
        cached = self._cache_get("streak_summary")
        if cached is not None:
            return cached

        today = datetime.now(self.timezone).date()
        period_start = today - timedelta(
            days=self.streak_lookback_days - 1
        )

        url = (
            self.contributions_url_template
            .replace("{username}", quote(self.username, safe=""))
            .replace("{from_date}", period_start.isoformat())
            .replace("{to_date}", today.isoformat())
        )

        async with self._client() as client:
            html = await self._request_text(client, url)

        contribution_days = self.parse_contribution_days(html)
        summary = self.calculate_streak_summary(
            contribution_days,
            period_start=period_start,
            period_end=today,
        )

        return self._cache_set("streak_summary", summary)

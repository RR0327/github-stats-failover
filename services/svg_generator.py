from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Iterable

from services.github_api import (
    LanguageItem,
    LanguageSummary,
    ProfileSummary,
    StreakSummary,
)


@dataclass(frozen=True)
class SvgTheme:
    background: str = "#ffffff"
    border: str = "#d0d7de"
    title: str = "#24292f"
    text: str = "#57606a"
    accent: str = "#0969da"
    muted: str = "#8c959f"
    track: str = "#eaeef2"


THEME = SvgTheme()


def _safe(value: object) -> str:
    return escape(str(value), quote=True)


def _number(value: int) -> str:
    return f"{value:,}"


def _timestamp(updated_at: datetime) -> str:
    return updated_at.strftime("%Y-%m-%d %H:%M %Z").strip()


def _svg_header(
    *,
    width: int,
    height: int,
    aria_label: str,
) -> str:
    return f"""
<svg xmlns="http://www.w3.org/2000/svg"
     width="{width}"
     height="{height}"
     viewBox="0 0 {width} {height}"
     role="img"
     aria-label="{_safe(aria_label)}">
  <rect x="0.5" y="0.5"
        width="{width - 1}" height="{height - 1}"
        rx="8"
        fill="{THEME.background}"
        stroke="{THEME.border}"/>
  <style>
    .title {{
      font: 700 20px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
      fill: {THEME.title};
    }}
    .label {{
      font: 500 13px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
      fill: {THEME.text};
    }}
    .value {{
      font: 700 22px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
      fill: {THEME.accent};
    }}
    .small {{
      font: 400 11px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
      fill: {THEME.muted};
    }}
  </style>
""".strip()


def render_stats_card(
    summary: ProfileSummary,
    *,
    updated_at: datetime,
) -> bytes:
    width = 495
    height = 195

    svg = f"""
{_svg_header(width=width, height=height, aria_label=f"GitHub statistics for {summary.login}")}
  <text x="24" y="38" class="title">{_safe(summary.name)}</text>
  <text x="24" y="59" class="label">@{_safe(summary.login)} · Python backup card</text>

  <text x="25" y="100" class="value">{_number(summary.public_repositories)}</text>
  <text x="25" y="121" class="label">Public repositories</text>

  <text x="150" y="100" class="value">{_number(summary.total_stars)}</text>
  <text x="150" y="121" class="label">Repository stars</text>

  <text x="275" y="100" class="value">{_number(summary.followers)}</text>
  <text x="275" y="121" class="label">Followers</text>

  <text x="390" y="100" class="value">{_number(summary.total_forks)}</text>
  <text x="390" y="121" class="label">Forks</text>

  <line x1="24" y1="145" x2="471" y2="145" stroke="{THEME.track}"/>
  <text x="24" y="169" class="small">
    Updated {_safe(_timestamp(updated_at))}
  </text>
</svg>
""".strip()

    return svg.encode("utf-8")


def _language_rows(
    items: Iterable[LanguageItem],
    *,
    top_count: int,
) -> str:
    rows: list[str] = []
    start_y = 78
    row_height = 26
    bar_x = 170
    bar_width = 250

    for index, item in enumerate(list(items)[:top_count]):
        y = start_y + (index * row_height)
        percentage = max(0.0, min(item.percentage, 100.0))
        filled_width = max(2.0, (percentage / 100.0) * bar_width)

        rows.append(
            f"""
  <text x="24" y="{y}" class="label">{_safe(item.name)}</text>
  <rect x="{bar_x}" y="{y - 11}" width="{bar_width}" height="9"
        rx="4.5" fill="{THEME.track}"/>
  <rect x="{bar_x}" y="{y - 11}" width="{filled_width:.1f}" height="9"
        rx="4.5" fill="{THEME.accent}"/>
  <text x="470" y="{y}" text-anchor="end" class="label">
    {percentage:.1f}%
  </text>
""".rstrip()
        )

    return "\n".join(rows)


def render_languages_card(
    summary: LanguageSummary,
    *,
    username: str,
    updated_at: datetime,
) -> bytes:
    width = 495
    top_count = min(6, len(summary.items))
    height = max(160, 105 + top_count * 26)

    svg = f"""
{_svg_header(width=width, height=height, aria_label=f"Top languages for {username}")}
  <text x="24" y="38" class="title">Most Used Languages</text>
  <text x="24" y="59" class="label">
    @{_safe(username)} · {summary.repositories_scanned} repositories scanned
  </text>

{_language_rows(summary.items, top_count=top_count)}

  <text x="24" y="{height - 18}" class="small">
    Updated {_safe(_timestamp(updated_at))}
  </text>
</svg>
""".strip()

    return svg.encode("utf-8")


def render_streak_card(
    summary: StreakSummary,
    *,
    username: str,
    updated_at: datetime,
) -> bytes:
    width = 495
    height = 195

    svg = f"""
{_svg_header(width=width, height=height, aria_label=f"Contribution streak for {username}")}
  <text x="24" y="38" class="title">GitHub Contribution Streak</text>
  <text x="24" y="59" class="label">
    @{_safe(username)} · rolling {summary.period_start} to {summary.period_end}
  </text>

  <text x="43" y="107" class="value">{_number(summary.total_contributions)}</text>
  <text x="43" y="130" class="label">Contributions</text>

  <text x="207" y="107" class="value">{_number(summary.current_streak)}</text>
  <text x="207" y="130" class="label">Current streak</text>

  <text x="365" y="107" class="value">{_number(summary.longest_streak)}</text>
  <text x="365" y="130" class="label">Longest streak</text>

  <line x1="24" y1="149" x2="471" y2="149" stroke="{THEME.track}"/>
  <text x="24" y="172" class="small">
    {summary.active_days} active days · Updated {_safe(_timestamp(updated_at))}
  </text>
</svg>
""".strip()

    return svg.encode("utf-8")


def render_permanent_safety_card(
    *,
    card_title: str,
    username: str,
    message: str,
) -> bytes:
    width = 495
    height = 195

    svg = f"""
{_svg_header(width=width, height=height, aria_label=f"{card_title} for {username}")}
  <text x="24" y="45" class="title">{_safe(card_title)}</text>
  <text x="24" y="73" class="label">@{_safe(username)}</text>

  <text x="24" y="117" class="value">GitHub Profile</text>
  <text x="24" y="143" class="label">{_safe(message)}</text>

  <text x="24" y="172" class="small">
    Permanent bundled safety card
  </text>
</svg>
""".strip()

    return svg.encode("utf-8")

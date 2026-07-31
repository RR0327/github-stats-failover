from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=False)

from services.failover import FailoverService, Settings  # noqa: E402


async def generate() -> int:
    settings = Settings.from_environment()
    service = FailoverService(settings)

    settings.fallback_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    successful_updates = 0

    for card_type in ("stats", "streak", "languages"):
        destination = service.snapshot_path(card_type)
        temporary = destination.with_suffix(".svg.tmp")

        try:
            card = await service.generate_live_backup(card_type)
            temporary.write_bytes(card.body)
            os.replace(temporary, destination)
        except Exception as exc:
            if temporary.exists():
                temporary.unlink()
            print(
                f"[FAILED] {card_type}: {exc}",
                file=sys.stderr,
            )
            continue

        successful_updates += 1
        print(
            f"[UPDATED] {card_type}: "
            f"{destination.relative_to(PROJECT_ROOT)}"
        )

    if successful_updates == 0:
        print(
            "No snapshots were updated. Existing snapshots were preserved.",
            file=sys.stderr,
        )
        return 1

    print(f"Updated {successful_updates} snapshot card(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(generate()))

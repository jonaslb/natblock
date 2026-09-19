from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import BlockWindow, Config

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def should_block(config: Config, now: datetime | None = None) -> bool:
    zone = ZoneInfo(config.timezone)
    current = now.astimezone(zone) if now else datetime.now(zone)

    return any(window_contains(window, current) for window in config.block_windows)


def window_contains(window: BlockWindow, current: datetime) -> bool:
    today = DAY_NAMES[current.weekday()]
    current_time = current.timetz().replace(tzinfo=None)

    if window.start < window.end:
        return today in window.days and window.start <= current_time < window.end

    yesterday = DAY_NAMES[(current - timedelta(days=1)).weekday()]
    return (today in window.days and current_time >= window.start) or (
        yesterday in window.days and current_time < window.end
    )

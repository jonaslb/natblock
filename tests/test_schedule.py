from datetime import datetime
from zoneinfo import ZoneInfo

from natblock.config import Config
from natblock.schedule import should_block


def config() -> Config:
    return Config.model_validate(
        {
            "device_mac": "02:00:00:00:00:01",
            "timezone": "Europe/Oslo",
            "block_windows": [
                {"days": ["sun", "mon", "tue", "wed", "thu"], "start": "22:30", "end": "07:00"},
                {"days": ["fri", "sat"], "start": "23:30", "end": "08:30"},
            ],
        }
    )


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo("Europe/Oslo"))


def test_overnight_window_uses_starting_day() -> None:
    assert should_block(config(), at("2026-09-20T22:30"))
    assert should_block(config(), at("2026-09-21T06:59"))
    assert not should_block(config(), at("2026-09-21T07:00"))


def test_weekend_window() -> None:
    assert not should_block(config(), at("2026-09-19T23:29"))
    assert should_block(config(), at("2026-09-19T23:30"))
    assert should_block(config(), at("2026-09-20T08:29"))
    assert not should_block(config(), at("2026-09-20T08:30"))


def test_mac_is_normalized() -> None:
    assert config().device_mac == "02-00-00-00-00-01"

from __future__ import annotations

import tomllib
from datetime import time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class BlockWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: set[Day]
    start: time
    end: time

    @model_validator(mode="after")
    def validate_window(self) -> BlockWindow:
        if not self.days:
            raise ValueError("days must not be empty")
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    router_url: str = "http://192.168.0.1"
    password_file: Path = Path("router_pass.txt")
    device_mac: str
    device_name: str | None = None
    profile_name: str = "natblock"
    timezone: str
    state_file: Path = Path("~/.local/state/natblock/state.json")
    block_windows: list[BlockWindow]

    @field_validator("device_mac")
    @classmethod
    def normalize_mac(cls, value: str) -> str:
        compact = value.replace(":", "").replace("-", "").upper()
        if len(compact) != 12 or any(char not in "0123456789ABCDEF" for char in compact):
            raise ValueError("device_mac must be a 12-digit MAC address")
        return "-".join(compact[index : index + 2] for index in range(0, 12, 2))

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown timezone: {value}") from error
        return value

    @field_validator("router_url")
    @classmethod
    def normalize_router_url(cls, value: str) -> str:
        return value.rstrip("/")


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError as error:
        raise ValueError(f"config file does not exist: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"invalid TOML in {path}: {error}") from error

    config = Config.model_validate(raw)
    config.password_file = config.password_file.expanduser()
    config.state_file = config.state_file.expanduser()
    if not config.password_file.is_absolute():
        config.password_file = path.parent / config.password_file
    if not config.state_file.is_absolute():
        config.state_file = path.parent / config.state_file
    return config

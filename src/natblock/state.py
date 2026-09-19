from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class State(BaseModel):
    snooze_until: datetime | None = None


def load_state(path: Path) -> State:
    try:
        return State.model_validate_json(path.read_text())
    except FileNotFoundError:
        return State()
    except (ValueError, OSError) as error:
        raise ValueError(f"cannot read state file {path}: {error}") from error


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state.model_dump(mode="json"), indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)

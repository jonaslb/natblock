from __future__ import annotations

import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from tplinkrouterc6u import ClientError, ClientException, TplinkRouterSG

PARENTAL_CONTROL_PATH = "admin/avira_parental_control?form=avira_pactrl"


class Device(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    mac: str
    online: bool
    owner_id: str = Field(alias="ownerId")
    client_type: str = Field(alias="clientType")

    @field_validator("owner_id", mode="before")
    @classmethod
    def owner_id_as_string(cls, value: object) -> str:
        return str(value)


class Profile(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    owner_id: str = Field(alias="ownerId")
    name: str
    internet_blocked: bool = Field(alias="internetBlocked")
    device_macs: list[str] = Field(alias="allDeviceMac")

    @model_validator(mode="before")
    @classmethod
    def derive_device_macs(cls, value: object) -> object:
        if not isinstance(value, dict) or "allDeviceMac" in value:
            return value
        clients = value.get("clientList", [])
        if isinstance(clients, str):
            clients = json.loads(clients)
        return {**value, "allDeviceMac": [client["mac"] for client in clients]}

    @field_validator("owner_id", mode="before")
    @classmethod
    def owner_id_as_string(cls, value: object) -> str:
        return str(value)

    @field_validator("device_macs", mode="before")
    @classmethod
    def parse_device_macs(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class RouterClient:
    def __init__(self, router_url: str, password_file: Path, lock_file: Path) -> None:
        try:
            password = password_file.read_text().strip()
        except OSError as error:
            raise RuntimeError(f"cannot read router password from {password_file}: {error}") from error
        if not password:
            raise RuntimeError(f"router password file is empty: {password_file}")
        self._router = TplinkRouterSG(router_url, password, timeout=15)
        self._lock_file = lock_file

    @contextmanager
    def session(self) -> Generator[RouterClient]:
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_file.open("a+") as lock:
            os.chmod(self._lock_file, 0o600)
            flock(lock, LOCK_EX)
            try:
                self._router.authorize()
                try:
                    yield self
                finally:
                    self._router.logout()
            except (ClientError, ClientException) as error:
                raise RuntimeError(f"router request failed: {error}") from error
            finally:
                flock(lock, LOCK_UN)

    def _request(self, **parameters: str) -> dict[str, object]:
        result = self._router.request(PARENTAL_CONTROL_PATH, urlencode(parameters))
        if not isinstance(result, dict):
            raise TypeError("router returned an unexpected response")
        return result

    def devices(self) -> list[Device]:
        data = self._request(operation="getDevicesList")
        clients = data.get("clientList", [])
        if not isinstance(clients, list):
            raise TypeError("router returned an invalid client list")
        return [Device.model_validate(item) for item in clients]

    def profiles(self) -> list[Profile]:
        data = self._request(operation="getOwnerTotalData")
        owners = data.get("ownerList", [])
        if isinstance(owners, str):
            owners = json.loads(owners)
        if isinstance(owners, dict):
            owners = list(owners.values())
        if not isinstance(owners, list):
            raise TypeError("router returned an invalid owner list")
        return [Profile.model_validate(item) for item in owners]

    def create_profile(self, name: str, device_mac: str) -> None:
        self._request(
            operation="addOwnerInList",
            ownerId="-1",
            name=name,
            age="18",
            internetBlocked="false",
            allDeviceMac=json.dumps([device_mac]),
            filterCategoriesList="[]",
            filterWebsiteList="[]",
            bedtime=json.dumps(
                {
                    "enable": False,
                    "everyday": {"bedtimeBegin": "1260", "bedtimeEnd": "420"},
                },
                separators=(",", ":"),
            ),
            filterFreeWebsiteList="[]",
        )

    def delete_profile(self, owner_id: str) -> None:
        self._request(operation="delOwnerInList", ownerList=json.dumps([owner_id]))

    def set_internet_blocked(self, owner_id: str, blocked: bool) -> None:
        self._request(
            operation="internetBlock",
            ownerId=owner_id,
            internetBlocked=json.dumps(blocked),
        )


def owned_profile(profiles: list[Profile], name: str, device_mac: str) -> Profile:
    matches = [profile for profile in profiles if profile.name == name]
    if not matches:
        raise RuntimeError(f"router profile {name!r} does not exist; run `natblock setup`")
    if len(matches) > 1:
        raise RuntimeError(f"multiple router profiles are named {name!r}; refusing to choose one")

    profile = matches[0]
    actual_macs = {mac.upper().replace(":", "-") for mac in profile.device_macs}
    if actual_macs != {device_mac}:
        raise RuntimeError(
            f"router profile {name!r} contains {sorted(actual_macs)}, not only {device_mac}; refusing to modify it"
        )
    return profile

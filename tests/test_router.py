from pathlib import Path

import pytest

from natblock.router import Device, Profile, RouterClient, owned_profile


def profile(*macs: str) -> Profile:
    return Profile.model_validate(
        {
            "ownerId": 3,
            "name": "natblock",
            "internetBlocked": False,
            "allDeviceMac": list(macs),
        }
    )


def test_owned_profile_accepts_exact_device() -> None:
    result = owned_profile([profile("02-00-00-00-00-01")], "natblock", "02-00-00-00-00-01")
    assert result.owner_id == "3"


def test_owned_profile_rejects_extra_device() -> None:
    with pytest.raises(RuntimeError, match="not only"):
        owned_profile(
            [profile("02-00-00-00-00-01", "02-00-00-00-00-02")],
            "natblock",
            "02-00-00-00-00-01",
        )


def test_device_accepts_numeric_unassigned_owner() -> None:
    device = Device.model_validate(
        {
            "name": "Streaming device",
            "mac": "02-00-00-00-00-01",
            "online": True,
            "ownerId": -1,
            "clientType": "Streaming Dongle",
        }
    )
    assert device.owner_id == "-1"


def test_profile_derives_macs_from_router_client_list() -> None:
    result = Profile.model_validate(
        {
            "ownerId": 3,
            "name": "natblock",
            "internetBlocked": 0,
            "clientList": '[{"mac":"02-00-00-00-00-01"}]',
        }
    )
    assert result.device_macs == ["02-00-00-00-00-01"]


def test_router_client_uses_private_lock_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("secret")
    lock_file = tmp_path / "state" / "router.lock"
    client = RouterClient("http://router.invalid", password_file, lock_file)
    monkeypatch.setattr(client._router, "authorize", lambda: None)
    monkeypatch.setattr(client._router, "logout", lambda: None)

    with client.session():
        assert lock_file.exists()

    assert lock_file.stat().st_mode & 0o777 == 0o600

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import ValidationError

from .config import Config, load_config
from .router import RouterClient, owned_profile
from .schedule import should_block
from .state import State, load_state, save_state

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
ConfigOption = Annotated[
    Path,
    typer.Option("--config", "-c", envvar="NATBLOCK_CONFIG", help="TOML configuration file."),
]


def settings(path: Path) -> Config:
    try:
        return load_config(path)
    except (ValueError, ValidationError) as error:
        raise typer.BadParameter(str(error), param_hint="--config") from error


def router_for(config: Config) -> RouterClient:
    return RouterClient(config.router_url, config.password_file)


def active_snooze(config: Config, now: datetime) -> datetime | None:
    state = load_state(config.state_file)
    if state.snooze_until and state.snooze_until > now:
        return state.snooze_until
    if state.snooze_until:
        save_state(config.state_file, State())
    return None


def set_access(config: Config, blocked: bool) -> bool:
    router = router_for(config)
    with router.session():
        profile = owned_profile(router.profiles(), config.profile_name, config.device_mac)
        if profile.internet_blocked == blocked:
            return False
        router.set_internet_blocked(profile.owner_id, blocked)
    return True


@app.command()
def discover(
    config_path: ConfigOption = Path("config.toml"),
) -> None:
    """List known devices and parental-control profiles without changing the router."""
    config = settings(config_path)
    router = router_for(config)
    with router.session():
        devices = router.devices()
        profiles = router.profiles()

    typer.echo("Devices:")
    for device in devices:
        marker = " * target" if device.mac.upper() == config.device_mac else ""
        typer.echo(
            f"  {device.mac}  {'online ' if device.online else 'offline'}  "
            f"{device.name} ({device.client_type}){marker}"
        )
    typer.echo("Profiles:")
    if not profiles:
        typer.echo("  (none)")
    for profile in profiles:
        state = "blocked" if profile.internet_blocked else "allowed"
        typer.echo(f"  {profile.owner_id}: {profile.name} [{state}] {', '.join(profile.device_macs)}")


@app.command()
def setup(
    config_path: ConfigOption = Path("config.toml"),
) -> None:
    """Create the dedicated router profile. This is the only setup mutation."""
    config = settings(config_path)
    router = router_for(config)
    with router.session():
        profiles = router.profiles()
        matches = [profile for profile in profiles if profile.name == config.profile_name]
        if matches:
            owned_profile(profiles, config.profile_name, config.device_mac)
            typer.echo(f"Profile {config.profile_name!r} already exists and is safe to use.")
            return

        devices = [device for device in router.devices() if device.mac.upper() == config.device_mac]
        if len(devices) != 1:
            raise RuntimeError(f"target MAC {config.device_mac} is not uniquely present in the router device list")
        if config.device_name and devices[0].name != config.device_name:
            raise RuntimeError(
                f"target MAC is named {devices[0].name!r}, expected {config.device_name!r}; refusing setup"
            )
        router.create_profile(config.profile_name, config.device_mac)
        try:
            profile = owned_profile(router.profiles(), config.profile_name, config.device_mac)
        except Exception:
            # Avoid leaving a malformed profile behind if firmware behavior changed.
            created = [profile for profile in router.profiles() if profile.name == config.profile_name]
            for profile in created:
                if {mac.upper().replace(":", "-") for mac in profile.device_macs} == {config.device_mac}:
                    router.delete_profile(profile.owner_id)
            raise
    typer.echo(f"Created router profile {profile.name!r} for {config.device_mac}; internet is allowed.")


@app.command("block")
def block_now(config_path: ConfigOption = Path("config.toml")) -> None:
    """Block the target immediately and cancel any snooze."""
    config = settings(config_path)
    save_state(config.state_file, State())
    changed = set_access(config, True)
    typer.echo("Internet blocked." if changed else "Internet was already blocked.")


@app.command("allow")
def allow_now(config_path: ConfigOption = Path("config.toml")) -> None:
    """Allow the target now; a later reconcile may apply the schedule again."""
    config = settings(config_path)
    changed = set_access(config, False)
    typer.echo("Internet allowed." if changed else "Internet was already allowed.")


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"([1-9][0-9]*)([mh])", value.strip().lower())
    if not match:
        raise typer.BadParameter("duration must look like 30m or 2h")
    amount = int(match.group(1))
    return timedelta(minutes=amount) if match.group(2) == "m" else timedelta(hours=amount)


@app.command()
def snooze(
    duration: Annotated[str, typer.Argument(help="Allow duration, such as 30m or 2h.")],
    config_path: ConfigOption = Path("config.toml"),
) -> None:
    """Temporarily allow internet regardless of the schedule."""
    config = settings(config_path)
    now = datetime.now(ZoneInfo(config.timezone))
    until = now + parse_duration(duration)
    save_state(config.state_file, State(snooze_until=until))
    set_access(config, False)
    typer.echo(f"Internet allowed until {until.isoformat(timespec='minutes')}.")


@app.command()
def resume(config_path: ConfigOption = Path("config.toml")) -> None:
    """Cancel a snooze and immediately apply the schedule."""
    config = settings(config_path)
    save_state(config.state_file, State())
    reconcile(config_path)


@app.command()
def reconcile(
    config_path: ConfigOption = Path("config.toml"),
    dry_run: Annotated[bool, typer.Option(help="Compute state without contacting the router.")] = False,
) -> None:
    """Make router state match the current schedule; intended for a timer."""
    config = settings(config_path)
    now = datetime.now(ZoneInfo(config.timezone))
    snoozed_until = active_snooze(config, now)
    desired_blocked = should_block(config, now) and snoozed_until is None
    desired = "blocked" if desired_blocked else "allowed"
    reason = f"snoozed until {snoozed_until.isoformat(timespec='minutes')}" if snoozed_until else "schedule"
    if dry_run:
        typer.echo(f"Desired state: {desired} ({reason}); router was not contacted.")
        return
    changed = set_access(config, desired_blocked)
    typer.echo(f"Internet {desired} ({reason}); router state {'changed' if changed else 'already matched'}.")


@app.command()
def status(config_path: ConfigOption = Path("config.toml")) -> None:
    """Show actual router state and the state currently desired by the schedule."""
    config = settings(config_path)
    now = datetime.now(ZoneInfo(config.timezone))
    snoozed_until = active_snooze(config, now)
    desired_blocked = should_block(config, now) and snoozed_until is None
    router = router_for(config)
    with router.session():
        profile = owned_profile(router.profiles(), config.profile_name, config.device_mac)
    typer.echo(
        json.dumps(
            {
                "actual": "blocked" if profile.internet_blocked else "allowed",
                "desired": "blocked" if desired_blocked else "allowed",
                "snooze_until": snoozed_until.isoformat() if snoozed_until else None,
                "profile": profile.name,
                "device_mac": config.device_mac,
            },
            indent=2,
        )
    )


def main() -> None:
    try:
        app()
    except (RuntimeError, TypeError, ValueError, OSError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

# natblock

`natblock` schedules internet access for a single device through a router's
per-device parental-control API. It is useful when software controls on the
device itself are unavailable, ineffective, or too easy to override.

One example is bedtime procrastination with a Google Chromecast or Google TV:
the device can remain connected to the local network while `natblock` pauses
its internet access overnight. The same approach can be used for televisions,
game consoles, tablets, and other devices identified by MAC address.

The tool is a desired-state reconciler. Each invocation computes whether the
device should currently be blocked, reads the router state, and changes it only
when necessary. A periodic systemd user timer therefore recovers naturally if
the computer was off when a block or allow boundary passed.

## Compatibility

The router integration is currently hardcoded for the encrypted local LuCI API
used by a TP-Link Archer BE550 v1.0 with firmware `1.2.4 Build 20260402
rel.18154(4555)`. It uses the router's HomeShield parental-control profile and
`internetBlock` operation. Other TP-Link models or firmware versions may use a
different API and are not supported unless tested.

The target remains associated with Wi-Fi and available on the LAN; the router
blocks only its internet access. `natblock` refuses to modify its named profile
unless that profile contains exactly the configured MAC address.

The router permits only one web-management session at a time. `natblock` logs
out promptly and serializes its own requests, but it can briefly conflict with
an open administration session. A failed timer run is retried at the next tick.

## Requirements

- Linux with a systemd user manager
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Network access to the router's HTTP management interface
- The router's local administrator password, not TP-Link cloud credentials

## Setup

Clone the repository and install its locked dependencies:

```console
git clone git@github.com:jonaslb/natblock.git ~/g/natblock
cd ~/g/natblock
uv sync --frozen
```

Create the local configuration and password file:

```console
cp config.example.toml config.toml
printf '%s\n' 'YOUR_LOCAL_ROUTER_PASSWORD' > router_pass.txt
chmod 600 router_pass.txt
```

Edit `config.toml`. Set the router address, target MAC, optional expected device
name, IANA timezone, and one or more block windows. Days identify the day on
which a window starts. This window blocks Sunday night through Friday morning:

```toml
router_url = "http://192.168.0.1"
password_file = "router_pass.txt"
device_mac = "02-00-00-00-00-01"
device_name = "Living Room TV"
profile_name = "natblock"
timezone = "Europe/London"
state_file = "~/.local/state/natblock/state.json"

[[block_windows]]
days = ["sun", "mon", "tue", "wed", "thu"]
start = "22:00"
end = "07:00"
```

Confirm that the router exposes the expected device before making changes:

```console
uv run natblock discover --config config.toml
uv run natblock reconcile --config config.toml --dry-run
```

Create a dedicated router profile and inspect it:

```console
uv run natblock setup --config config.toml
uv run natblock status --config config.toml
```

`setup` is the only initialization mutation. It creates the profile with the
configured device and leaves internet access enabled. Repeating it is safe.

## Commands

```console
uv run natblock discover -c config.toml
uv run natblock status -c config.toml
uv run natblock reconcile -c config.toml
uv run natblock block -c config.toml
uv run natblock allow -c config.toml
uv run natblock snooze 45m -c config.toml
uv run natblock resume -c config.toml
```

`block` cancels any snooze and blocks immediately. `allow` allows immediately,
but the next reconcile can restore the scheduled state. `snooze` persists an
allow-until timestamp across timer runs; `resume` clears it and reapplies the
schedule.

## systemd User Timer

The included timer reconciles every two minutes. Update the paths in
`systemd/natblock.service` if the checkout is not at `~/g/natblock`, then run:

```console
mkdir -p ~/.config/systemd/user
cp systemd/natblock.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now natblock.timer
systemctl --user start natblock.service
systemctl --user status natblock.timer
journalctl --user -u natblock.service
```

To run the user timer while logged out, enable lingering once:

```console
loginctl enable-linger "$USER"
```

## Development

```console
uv sync --all-groups
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen pyrefly check
```

The router API is undocumented and firmware-specific. Re-run `discover` and
test a reversible `block`/`allow` cycle after firmware upgrades.

## License

MIT. See `LICENSE`.

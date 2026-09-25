# ZTE Kids Integration for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/jkaberg/hass-zte-kids)](https://github.com/jkaberg/hass-zte-kids/releases/latest)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/jkaberg/hass-zte-kids/actions/workflows/validate.yml/badge.svg)](https://github.com/jkaberg/hass-zte-kids/actions/workflows/validate.yml)
[![Quality](https://github.com/jkaberg/hass-zte-kids/actions/workflows/quality.yml/badge.svg)](https://github.com/jkaberg/hass-zte-kids/actions/workflows/quality.yml)
[![License](https://img.shields.io/github/license/jkaberg/hass-zte-kids)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/jkaberg)

Home Assistant custom integration for ZTE Kids watches.

## Installation

### Option 1: HACS (Custom Repository)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jkaberg&repository=hass-zte-kids&category=Integration)

1. Open HACS -> Integrations.
2. Open the menu (...) -> Custom repositories.
3. Add `https://github.com/jkaberg/hass-zte-kids` as `Integration`.
4. Install `ZTE Kids`.
5. Restart Home Assistant.
6. Add `ZTE Kids` from `Settings -> Devices & Services`.

### Option 2: Manual

1. Open your Home Assistant config directory.
2. Create `custom_components/` if needed.
3. Copy `custom_components/zte_kids/` from this repository into your Home Assistant config.
4. Restart Home Assistant.
5. Add `ZTE Kids` from `Settings -> Devices & Services`.

## Initial setup

Configuration is UI-only via the Home Assistant config flow.

> [!TIP]
> Use a dedicated ZTE Kids account for the integration. Logging in through Home Assistant will invalidate the session in the mobile app, so using a dedicated account helps avoid being logged out on your main account.

> [!IMPORTANT]
> If the upstream account requires an interactive captcha or verification challenge, setup will abort. The integration can detect that flow, but Home Assistant cannot complete it.

| Field | Required | Default | Description |
|---|---|---|---|
| Username | Yes | - | ZTE Kids account username or email. |
| Password | Yes | - | Account password used in the mobile app. |

> [!TIP]
> If authentication fails, verify the username and password first. If those are correct, retry from the app and check whether the account is being forced through a captcha challenge.

## How data stays fresh

Two paths deliver state: an HTTP poll, which reads everything, and an optional
real-time event stream from the vendor's broker, which only ever carries a
position fix or a battery level.

The polling interval is a promise about **how old data may get**, not how often
a request is sent. Each watch tracks when its position, battery and remaining
status were last current; whichever goes stale first triggers a poll. An event
that delivers a fix satisfies the position deadline and defers the request, so
a working stream means fewer HTTP calls and fresher positions, while a stream
that goes quiet costs nothing — the deadlines expire on their own and polling
resumes at exactly the configured rate.

Being connected to the broker earns no reduction on its own. A broker can
accept a connection and then send nothing, and only data that has actually
arrived is allowed to move a deadline. Config, step totals and unread counts
are never pushed, so a poll still runs at least every 30 minutes (or the
configured interval, if that is longer) to keep them current.

Real-time push can be turned off in the integration's options without losing
anything; polling alone then meets the same deadlines.

## Available entities

Each watch on the account becomes one Home Assistant device with around 27
entities, depending on what the watch reports it can do.

### Sensors

| Entity | Notes |
|---|---|
| `device_tracker` | GPS position, with address and accuracy as attributes. |
| `sensor` Battery | Percentage, as last reported by the watch. |
| `sensor` Steps | Step count from the device list. |
| `sensor` Distance today / Calories today | From the watch's daily activity totals. |
| `sensor` Unread messages | Unread count for this watch. |
| `sensor` Location updated | When the watch last reported a fix. Use this to tell a fresh position from a stale one. |
| `binary_sensor` per safe zone | Whether the watch is inside a configured safe zone. |
| `update` Firmware | Installed and available firmware; installing tells the watch to start upgrading. |

Safe-zone occupancy is computed locally from the watch's position against the
zone's centre and radius, because the service only pushes enter/exit events.
That keeps it correct at any polling interval.

### Actions

| Entity | What it does |
|---|---|
| `button` Locate now | Asks the watch for a fresh fix, then re-checks a few times over ~45 seconds. |
| `button` Refresh data | Re-reads the account from the API without waking the watch. |
| `button` Find watch | Makes the watch ring. |
| `button` Restart watch | Reboots the watch. |
| `button` Power off watch | Powers the watch off. **Disabled by default** — see below. |
| `notify` Message | Sends a text message to the watch. |

Send a message from an automation with the standard notify action:

```yaml
action: notify.send_message
target:
  entity_id: notify.watch_1_message
data:
  message: "Home by six please"
```

> [!WARNING]
> **Power off** is disabled by default because a watch that has been powered
> off remotely can only be switched back on by hand — until someone reaches the
> child, there is no location tracking. Enable it from the device page if you
> want it. **Restart** is not disabled, because the watch comes back on its own.

> [!NOTE]
> A command succeeding means the ZTE service accepted it, not that the watch
> carried it out. The watch has to be online and connected for a command to
> take effect, exactly as in the mobile app.

Ring, restart and power off are rate limited to one every 5 seconds per watch
and are rejected rather than queued if pressed faster. Settings writes are not
rate limited, so a script can set several in a row.

### Settings

| Entity | Setting |
|---|---|
| `select` Location mode | Precision / Normal / Power saving. Precision costs the most battery. |
| `switch` Battery saver | Long-life mode. |
| `switch` Auto answer calls | |
| `switch` Call whitelist | Only accept calls from known contacts. |
| `switch` Receive SMS / SMS from family only | |
| `switch` Scheduled power off | Uses the window set by the service below. |
| `switch` Shutdown protection | Requires a code on the watch before it powers off. |
| `switch` Task reminder | |
| `number` Step goal | Daily step target. |
| `number` Polling interval, `switch` Polling enabled | Per-watch freshness, 5 to 60 minutes. See [How data stays fresh](#how-data-stays-fresh). |

Five permission switches (location, battery, SMS, activity, app management) are
also created as diagnostic entities, disabled by default. They gate whole
subsystems on the watch and most people should never touch them.

### Services

Some settings are transactional — the wire format carries the whole object, so
the SOS set is one write of three numbers and the power-off window is one write
of a switch and both ends. Splitting those across one entity per field would
turn a single change into several partial ones, so they are services instead:

| Service | Sets |
|---|---|
| `zte_kids.set_sos_numbers` | The three SOS numbers. |
| `zte_kids.set_power_off_schedule` | Scheduled power-off window. |
| `zte_kids.set_shutdown_protection` | Shutdown protection and its code. |
| `zte_kids.set_task_reminder` | Task reminder state and time. |
| `zte_kids.set_permissions` | The watch's feature permissions. |

```yaml
action: zte_kids.set_sos_numbers
data:
  device_id: "{{ device_id('device_tracker.watch_1') }}"
  number_1: "+4712345678"
  number_2: "+4787654321"
```

## Debug logging

To inspect signed API requests, responses, and polling decisions, enable debug logging for the integration loggers in Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.zte_kids.coordinator: debug
    custom_components.zte_kids.sdk.http: debug
```

What each logger shows:

- `custom_components.zte_kids.coordinator`: polling decisions, skipped snapshot updates, and force-refresh behavior.
- `custom_components.zte_kids.sdk.http`: outbound request method/path plus redacted query/body/header data, and redacted JSON responses.

Debug logs redact secrets and personal data — tokens, SOS numbers, the
shutdown code, coordinates and addresses are replaced, and identifiers such as
the IMEI keep only their last four characters so lines stay correlatable.

For bug reports, prefer the integration's **Download diagnostics** button on
the config entry — it captures the same state with the same redaction.
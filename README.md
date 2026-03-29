# ZTE Kids Integration for Home Assistant

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

## Available sensors

- Device tracker (GPS based)
- Battery %
- Steps counter

Polling is configurable with a per-device input number and enable/disable switch. The supported range is 5 to 60 minutes. There is also a "Force refresh" button.

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
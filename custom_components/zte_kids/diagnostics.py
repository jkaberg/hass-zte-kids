"""Diagnostics support for ZTE Kids."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ZTEKidsConfigEntry

# Coordinates are redacted along with credentials: a diagnostics file is
# usually attached to a public issue, and this one tracks a child.
TO_REDACT = {
    "accesstoken",
    "access_token",
    "address",
    "address_poi",
    "avator",
    "bindNo",
    "bindUrl",
    "esimid",
    "imei",
    "lat",
    "latitude",
    "lon",
    "longitude",
    "openid",
    "password",
    "phone",
    "real_name",
    "shutdownPwd",
    "sos1",
    "sos2",
    "sos3",
    "token",
    "username",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data

    devices: dict[str, Any] = {}
    for index, (device_id, snapshot) in enumerate(data.devices.items()):
        devices[f"device_{index}"] = {
            "model": snapshot.device.model,
            "is_admin": snapshot.device.is_admin,
            "battery": snapshot.battery,
            "steps": snapshot.steps,
            "has_location": snapshot.location is not None,
            "capabilities": asdict(coordinator.device_capabilities(device_id)),
            "polling_enabled": coordinator.device_polling_enabled(device_id),
            "polling_interval": coordinator.device_polling_interval(device_id),
            "raw": async_redact_data(snapshot.raw, TO_REDACT),
            "config": async_redact_data(snapshot.config, TO_REDACT),
        }

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "update_interval": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval is not None
            else None
        ),
        "last_update_success": coordinator.last_update_success,
        "device_count": len(data.devices),
        "devices": devices,
    }

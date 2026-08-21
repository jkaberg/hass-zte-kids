"""Actions for settings that do not fit the entity model.

Some of this watch's settings are transactional: the wire format carries the
whole object, so the SOS set is one write of three numbers and the power-off
window is one write of a switch and both ends. Splitting those across one
entity per field turns a single atomic change into several partial ones, each
briefly leaving the watch in a state the user never asked for.

These settings are also set-once-and-forget, which is not what entities are
for. They live here instead, and the entity platforms keep the scalars that
are genuinely worth automating and graphing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import ZTEKidsDataUpdateCoordinator

SERVICE_SET_SOS_NUMBERS = "set_sos_numbers"
SERVICE_SET_POWER_OFF_SCHEDULE = "set_power_off_schedule"
SERVICE_SET_SHUTDOWN_PROTECTION = "set_shutdown_protection"
SERVICE_SET_TASK_REMINDER = "set_task_reminder"
SERVICE_SET_PERMISSIONS = "set_permissions"

ATTR_DEVICE_ID = "device_id"

_PHONE = vol.All(cv.string, vol.Length(max=20))
_TIME = vol.All(cv.string, vol.Match(r"^\d{1,2}:\d{2}(:\d{2})?$"))

_TARGET = {vol.Required(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string])}

SOS_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Optional("number_1"): _PHONE,
        vol.Optional("number_2"): _PHONE,
        vol.Optional("number_3"): _PHONE,
    }
)

POWER_OFF_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("start_time"): _TIME,
        vol.Optional("end_time"): _TIME,
    }
)

SHUTDOWN_PROTECTION_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("password"): vol.All(cv.string, vol.Match(r"^\d{4}$")),
    }
)

TASK_REMINDER_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("time"): _TIME,
    }
)

PERMISSIONS = ("location", "battery", "sms", "activity", "apps")

PERMISSIONS_SCHEMA = vol.Schema(
    {
        **_TARGET,
        **{vol.Optional(name): cv.boolean for name in PERMISSIONS},
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions. Safe to call more than once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_SOS_NUMBERS):
        return

    hass.services.async_register(
        DOMAIN, SERVICE_SET_SOS_NUMBERS, _async_set_sos_numbers, schema=SOS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POWER_OFF_SCHEDULE,
        _async_set_power_off_schedule,
        schema=POWER_OFF_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SHUTDOWN_PROTECTION,
        _async_set_shutdown_protection,
        schema=SHUTDOWN_PROTECTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TASK_REMINDER,
        _async_set_task_reminder,
        schema=TASK_REMINDER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PERMISSIONS, _async_set_permissions, schema=PERMISSIONS_SCHEMA
    )


async def _async_set_sos_numbers(call: ServiceCall) -> None:
    for coordinator, watch_id in _targets(call):
        current = list(coordinator.device_config(watch_id).sos.numbers)
        for index, key in enumerate(("number_1", "number_2", "number_3")):
            if key in call.data:
                current[index] = call.data[key] or None
        await coordinator.async_set_sos_numbers(
            watch_id, (current[0], current[1], current[2])
        )


async def _async_set_power_off_schedule(call: ServiceCall) -> None:
    for coordinator, watch_id in _targets(call):
        await coordinator.async_set_scheduled_power_off(
            watch_id,
            enabled=call.data.get("enabled"),
            start_time=_normalise_time(call.data.get("start_time")),
            end_time=_normalise_time(call.data.get("end_time")),
        )


async def _async_set_shutdown_protection(call: ServiceCall) -> None:
    for coordinator, watch_id in _targets(call):
        await coordinator.async_set_shutdown_protection(
            watch_id,
            enabled=call.data.get("enabled"),
            password=call.data.get("password"),
        )


async def _async_set_task_reminder(call: ServiceCall) -> None:
    for coordinator, watch_id in _targets(call):
        await coordinator.async_set_task_reminder(
            watch_id,
            enabled=call.data.get("enabled"),
            time=_normalise_time(call.data.get("time")),
        )


async def _async_set_permissions(call: ServiceCall) -> None:
    requested = {name: call.data[name] for name in PERMISSIONS if name in call.data}
    if not requested:
        return
    for coordinator, watch_id in _targets(call):
        await coordinator.async_set_permissions(watch_id, requested)


def _normalise_time(value: str | None) -> str | None:
    """Reduce ``HH:MM:SS`` to the ``HH:MM`` the watch expects."""
    if value is None:
        return None
    parts = value.split(":")
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


def _targets(call: ServiceCall) -> list[tuple[ZTEKidsDataUpdateCoordinator, str]]:
    """Resolve the call's device targets to (coordinator, watch id) pairs."""
    raw = call.data[ATTR_DEVICE_ID]
    device_ids = [raw] if isinstance(raw, str) else list(raw)

    registry = dr.async_get(call.hass)
    resolved: list[tuple[ZTEKidsDataUpdateCoordinator, str]] = []

    for device_id in device_ids:
        entry = registry.async_get(device_id)
        if entry is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_device",
                translation_placeholders={"device_id": device_id},
            )

        watch_id = next(
            (value for domain, value in entry.identifiers if domain == DOMAIN), None
        )
        coordinator = _coordinator_for(call.hass, entry.config_entries)
        if watch_id is None or coordinator is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_device",
                translation_placeholders={"device_id": device_id},
            )
        resolved.append((coordinator, watch_id))

    return resolved


def _coordinator_for(
    hass: HomeAssistant, config_entry_ids: Any
) -> ZTEKidsDataUpdateCoordinator | None:
    for entry_id in config_entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is not None
            and entry.domain == DOMAIN
            and entry.state is ConfigEntryState.LOADED
        ):
            return entry.runtime_data.coordinator
    return None

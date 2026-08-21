"""Command vocabulary for the multiplexed device command endpoint.

``POST api/device/save/systemconfig`` carries every device operation. The
``type`` field selects the operation and the rest of the body varies per
family, so each family gets its own builder rather than a single flat
``type -> status`` mapping.

Every value here was recovered from ``com.nubia.care`` 2.4.7.A. Where the
call site was a generic sender (``RemoteControlActivity.L4(int)``) the meaning
was confirmed against the confirmation dialog string the button is wired to,
not inferred from the surrounding class name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class CommandType(IntEnum):
    """Operation selector for ``api/device/save/systemconfig``."""

    LOCATION_MODE = 1
    LONG_LIFE_MODE = 2
    CALL_WHITELIST = 3
    FIND_WATCH = 4
    AUTO_ANSWER = 5
    DO_NOT_DISTURB = 6
    POWER_OFF = 7
    APP_MANAGEMENT = 8
    SMS_RECEIVE = 9
    FIRMWARE_UPGRADE = 11
    SOS_NUMBERS = 12
    RESTART = 13
    POSITION_PERMISSION = 14
    BATTERY_PERMISSION = 15
    SMS_PERMISSION = 16
    SPORTS_PERMISSION = 17
    APP_PERMISSION = 18
    SCHEDULED_POWER_OFF = 19
    SMS_MEMBERS_ONLY = 20
    SHUTDOWN_PROTECTION = 25
    TASK_REMINDER = 26


class LocationMode(IntEnum):
    """``mode`` values for :attr:`CommandType.LOCATION_MODE`.

    Names follow the labels the app shows for each value, recovered from
    ``BatterySavingActivity.I4()``.
    """

    PRECISION = 1
    NORMAL = 2
    POWER_SAVING = 3


#: Option strings exposed to Home Assistant, in the app's own wording.
LOCATION_MODE_OPTIONS: dict[str, LocationMode] = {
    "precision": LocationMode.PRECISION,
    "normal": LocationMode.NORMAL,
    "power_saving": LocationMode.POWER_SAVING,
}


#: Wire values for a two-state setting.
#:
#: Proven from ``SmsReceiveSettingsActivity.G4()``: a value of ``1`` renders
#: ``checkbox_selected.png`` and reveals the dependent sub-setting, anything
#: else renders ``checkbox_no_select.png`` and hides it. ``a4.b.K()`` toggles
#: strictly between the two.
SWITCH_ON = 1
SWITCH_OFF = 2


def switch_to_bool(value: Any) -> bool | None:
    """Interpret a ``status`` field, returning ``None`` for unknown values.

    Only ``1`` and ``2`` have a proven meaning. Values outside that domain are
    reported as unknown rather than coerced, because no evidence says the
    domain is strictly binary on every device model.
    """
    if value is None:
        return None
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    if status == SWITCH_ON:
        return True
    if status == SWITCH_OFF:
        return False
    return None


def bool_to_switch(value: bool) -> int:
    """Render a boolean as the wire ``status`` value."""
    return SWITCH_ON if value else SWITCH_OFF


@dataclass(frozen=True, slots=True)
class Command:
    """A single device command, ready to be serialised for a device."""

    command_type: CommandType
    payload: dict[str, Any] = field(default_factory=dict)

    def body(self, device_id: str) -> dict[str, Any]:
        """Build the request body for ``device_id``.

        The transport adds ``token``; everything else is here.
        """
        return {
            "deviceId": device_id,
            "type": int(self.command_type),
            **self.payload,
        }


def one_shot(command_type: CommandType) -> Command:
    """A fire-and-forget command carrying no payload beyond the selector."""
    return Command(command_type)


def switch(command_type: CommandType, enabled: bool) -> Command:
    """A ``status``-shaped on/off command."""
    return Command(command_type, {"status": bool_to_switch(enabled)})


def mode(command_type: CommandType, value: int) -> Command:
    """A ``mode``-shaped command. Only location mode uses this shape."""
    return Command(command_type, {"mode": int(value)})


def nested(command_type: CommandType, key: str, value: dict[str, Any]) -> Command:
    """A command carrying a nested object such as ``sos`` or ``shutdownVo``."""
    return Command(command_type, {key: value})


def scheduled_power_off(*, enabled: bool, start_time: str, end_time: str) -> Command:
    """Scheduled power-off.

    This is the one command that does not share ``ModifyConfigRequest``'s
    shape: the app sends a dedicated request class with the window nested
    under ``rule.interval``.
    """
    return Command(
        CommandType.SCHEDULED_POWER_OFF,
        {
            "status": bool_to_switch(enabled),
            "rule": {"interval": {"startTime": start_time, "endTime": end_time}},
        },
    )


def shutdown_protection(*, enabled: bool, password: str | None) -> Command:
    """Shutdown-protection switch and its 4-digit password.

    The nested object carries both fields, so a caller changing one must send
    the other unchanged.
    """
    payload: dict[str, Any] = {"status": bool_to_switch(enabled)}
    if password is not None:
        payload["shutdownPwd"] = password
    return nested(CommandType.SHUTDOWN_PROTECTION, "shutdownVo", payload)


def sos_numbers(numbers: tuple[str | None, str | None, str | None]) -> Command:
    """Save the SOS phone set.

    The app sends the whole set rather than the changed entry, so callers must
    pass all three.
    """
    return nested(
        CommandType.SOS_NUMBERS,
        "sos",
        {
            "sos1": numbers[0] or "",
            "sos2": numbers[1] or "",
            "sos3": numbers[2] or "",
        },
    )


FIND_WATCH = one_shot(CommandType.FIND_WATCH)
POWER_OFF = one_shot(CommandType.POWER_OFF)
RESTART = one_shot(CommandType.RESTART)
START_FIRMWARE_UPGRADE = one_shot(CommandType.FIRMWARE_UPGRADE)

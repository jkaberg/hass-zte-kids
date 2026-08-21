"""Typed views over device capability flags and the device config object."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..commands import switch_to_bool

CAPABILITY_FIELDS: dict[str, str] = {
    "alarm": "support_alarm",
    "bt_avoid_losing": "support_BT_Avoid_Losing",
    "call_phone": "support_callPhone",
    "chat": "support_chat",
    "cost_flow": "support_costFlow",
    "disturb": "support_disturb",
    "family": "support_family",
    "find": "support_find",
    "flower": "support_flower",
    "health_code": "support_healthCode",
    "heart_rate": "support_heartRate",
    "mcloud": "support_mcloud",
    "monitor": "support_monitor",
    "photo": "support_photo",
    "safe_area": "support_safeArea",
    "sos": "support_sos",
    "step": "support_step",
    "temperature": "support_temperature",
    "timing_switch": "support_timingSwitch",
    "video": "support_video",
    "voucher_center": "support_voucherCenter",
    "white_list": "support_whiteList",
    "wifi": "support_wifi",
}


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    """What a watch advertises that it can do.

    Capability flags travel as integers, not booleans, and no universal value
    mapping has been proven across device models. The raw integers are kept as
    the canonical representation and :meth:`supports` is a deliberately
    conservative derived view.

    A capability flag is also not the same thing as permission to use the
    feature: the account's ``permissions`` string and admin status gate
    management actions independently.
    """

    support: dict[str, int] = field(default_factory=dict)
    permissions_raw: str | None = None
    identity: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "DeviceCapabilities":
        if not isinstance(payload, Mapping):
            return cls()

        support: dict[str, int] = {}
        for name, wire_key in CAPABILITY_FIELDS.items():
            value = payload.get(wire_key)
            if value is None:
                continue
            try:
                support[name] = int(value)
            except (TypeError, ValueError):
                continue

        permissions = payload.get("permissions")
        identity = payload.get("identity")
        return cls(
            support=support,
            permissions_raw=permissions if isinstance(permissions, str) else None,
            identity=identity if isinstance(identity, str) else None,
        )

    def supports(self, feature: str, *, default: bool = True) -> bool:
        """Whether ``feature`` is advertised.

        Unknown features fall back to ``default``. Older firmware omits
        capability flags entirely, so an absent flag is treated as "probably
        supported" rather than hiding an entity the watch can actually use.
        """
        value = self.support.get(feature)
        if value is None:
            return default
        return value != 0


@dataclass(frozen=True, slots=True)
class ShutdownProtection:
    enabled: bool | None = None
    password: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "ShutdownProtection":
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            enabled=switch_to_bool(payload.get("status")),
            password=payload.get("shutdownPwd"),
        )


@dataclass(frozen=True, slots=True)
class SosNumbers:
    numbers: tuple[str | None, str | None, str | None] = (None, None, None)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "SosNumbers":
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            numbers=(
                payload.get("sos1"),
                payload.get("sos2"),
                payload.get("sos3"),
            )
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "sos1": self.numbers[0] or "",
            "sos2": self.numbers[1] or "",
            "sos3": self.numbers[2] or "",
        }


@dataclass(frozen=True, slots=True)
class TaskReminder:
    enabled: bool | None = None
    time: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "TaskReminder":
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            enabled=switch_to_bool(payload.get("reminderStatus")),
            time=payload.get("reminderTime"),
        )


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """Typed view over the ``ConfigData`` object.

    Only the fields with a settled meaning are surfaced. ``raw`` is preserved
    in full so that nothing recovered from the server is lost, and so that
    unmapped fields stay inspectable through diagnostics.
    """

    location_mode: int | None = None
    long_life_mode: bool | None = None
    call_whitelist: bool | None = None
    auto_answer: bool | None = None
    sms_receive: bool | None = None
    sms_members_only: bool | None = None
    position_permission: bool | None = None
    battery_permission: bool | None = None
    sms_permission: bool | None = None
    sports_permission: bool | None = None
    app_permission: bool | None = None
    scheduled_power_off: bool | None = None
    scheduled_power_off_start: str | None = None
    scheduled_power_off_end: str | None = None
    shutdown_protection: ShutdownProtection = field(default_factory=ShutdownProtection)
    task_reminder: TaskReminder = field(default_factory=TaskReminder)
    sos: SosNumbers = field(default_factory=SosNumbers)
    battery: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "DeviceConfig":
        if not isinstance(payload, Mapping):
            return cls()

        battery_payload = payload.get("battery")
        battery = None
        if isinstance(battery_payload, Mapping):
            battery = _coerce_int(battery_payload.get("percent"))

        return cls(
            location_mode=_coerce_int(payload.get("locMode")),
            long_life_mode=switch_to_bool(payload.get("longLifeMode")),
            call_whitelist=switch_to_bool(payload.get("callWhitelist")),
            auto_answer=switch_to_bool(payload.get("autoAnswer")),
            sms_receive=switch_to_bool(payload.get("sms")),
            sms_members_only=switch_to_bool(payload.get("smsReceiveOnlyMember")),
            position_permission=switch_to_bool(payload.get("positionSwitch")),
            battery_permission=switch_to_bool(payload.get("batterySwitch")),
            sms_permission=switch_to_bool(payload.get("smsSwitch")),
            sports_permission=switch_to_bool(payload.get("sportsSwitch")),
            app_permission=switch_to_bool(payload.get("appSwitch")),
            scheduled_power_off=switch_to_bool(payload.get("bootOffSwitch")),
            scheduled_power_off_start=payload.get("bootOffStartTime"),
            scheduled_power_off_end=payload.get("bootOffEndTime"),
            shutdown_protection=ShutdownProtection.from_payload(payload.get("shutdownVO")),
            task_reminder=TaskReminder.from_payload(payload.get("taskReminderVO")),
            sos=SosNumbers.from_payload(payload.get("sos")),
            battery=battery,
            raw=dict(payload),
        )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str
    openid: str | None = None
    name: str | None = None
    relationship: str | None = None
    model: str | None = None
    group_id: str | None = None
    single_group_id: str | None = None
    is_admin: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Device:
        device_id = _first_present(payload, "imei", "deviceId", "id")
        return cls(
            device_id=str(device_id or ""),
            openid=payload.get("openid"),
            name=payload.get("deviceDefaultName")
            or payload.get("name")
            or payload.get("device_name"),
            relationship=payload.get("relationship"),
            model=payload.get("model"),
            group_id=payload.get("groupid"),
            single_group_id=_first_present(payload, "singleGroupId", "single_groupid"),
            is_admin=_coerce_admin(payload),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class DeviceLocation:
    latitude: float
    longitude: float
    address: str | None = None
    address_poi: str | None = None
    radius: int | None = None
    timestamp: int | None = None
    loc_type: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DeviceLocation | None:
        lat = _first_present(payload, "lat", "latitude")
        lon = _first_present(payload, "lon", "longitude")
        if lat is None or lon is None:
            return None
        return cls(
            latitude=float(lat),
            longitude=float(lon),
            address=payload.get("address"),
            address_poi=payload.get("address_poi"),
            radius=_coerce_int(payload.get("radius")),
            timestamp=_coerce_int(payload.get("timestamp")),
            loc_type=payload.get("loc_type") or payload.get("type"),
        )


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    device: Device
    battery: int | None = None
    battery_timestamp: int | None = None
    steps: int | None = None
    location: DeviceLocation | None = None
    config: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DeviceSnapshot:
        battery_payload = _mapping_or_none(payload.get("battery"))
        location_payload = _mapping_or_none(payload.get("lastLocation")) or _mapping_or_none(
            payload.get("location")
        )
        battery = _first_non_none(
            payload.get("electricity"),
            payload.get("battery") if battery_payload is None else None,
            battery_payload.get("percent") if battery_payload is not None else None,
        )
        steps = _first_non_none(
            payload.get("step"),
            payload.get("step_num"),
            payload.get("steps"),
            payload.get("sportStep"),
            payload.get("stepNum"),
            payload.get("totalStep"),
        )
        location = DeviceLocation.from_payload(
            _merge_dicts(payload, location_payload) if location_payload is not None else payload
        )
        return cls(
            device=Device.from_payload(payload),
            battery=_coerce_int(battery),
            battery_timestamp=_coerce_int(
                battery_payload.get("updateTime") if battery_payload is not None else None
            ),
            steps=_coerce_int(steps),
            location=location,
            config=payload.get("config") if isinstance(payload.get("config"), dict) else {},
            raw=payload,
        )


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return None


def _coerce_admin(payload: dict[str, Any]) -> bool | None:
    explicit = _coerce_bool(payload.get("isAdmin"))
    if explicit is not None:
        return explicit

    identity = payload.get("identity")
    if isinstance(identity, str):
        lowered = identity.strip().lower()
        if lowered == "admin":
            return True
        if lowered:
            return False
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

"""Safe zones ("security guard" rules).

Enter and exit are delivered as push events, so a polling client cannot observe
the transition. It does not need to: the rule carries its own centre and
radius, so occupancy is computed locally from the watch's reported position.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any

from ..commands import switch_to_bool

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class GuardArea:
    """One circle belonging to a rule."""

    latitude: float
    longitude: float
    radius_m: float
    name: str | None = None

    def contains(self, latitude: float, longitude: float) -> bool:
        return haversine_m(latitude, longitude, self.latitude, self.longitude) <= self.radius_m


@dataclass(frozen=True, slots=True)
class GuardRule:
    rule_id: str
    name: str | None = None
    enabled: bool | None = None
    areas: tuple[GuardArea, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GuardRule | None":
        rule_id = payload.get("securityGuardId")
        if not rule_id:
            return None

        areas: list[GuardArea] = []
        addresses = payload.get("addr")
        if isinstance(addresses, list):
            for address in addresses:
                if not isinstance(address, Mapping):
                    continue
                areas.extend(_parse_areas(address))

        return cls(
            rule_id=str(rule_id),
            name=payload.get("ruleName"),
            enabled=switch_to_bool(payload.get("status")),
            areas=tuple(areas),
            raw=dict(payload),
        )

    def contains(self, latitude: float, longitude: float) -> bool:
        return any(area.contains(latitude, longitude) for area in self.areas)


def _parse_areas(address: Mapping[str, Any]) -> list[GuardArea]:
    """Parse an ``Address`` into circles.

    ``coordinate`` packs points as ``lon,lat`` separated by ``;`` — longitude
    first. Confirmed from ``DrawAllRegionActivity.v4()``, which splits on ``;``
    then ``,`` and passes ``part[1]`` as the latitude.
    """
    coordinate = address.get("coordinate")
    if not isinstance(coordinate, str) or not coordinate.strip():
        return []

    radius = _coerce_float(address.get("addrRange")) or 0.0
    if radius <= 0:
        return []

    name = address.get("addrName") or address.get("addrDetail")
    areas: list[GuardArea] = []
    for point in coordinate.split(";"):
        parts = point.split(",")
        if len(parts) < 2:
            continue
        longitude = _coerce_float(parts[0])
        latitude = _coerce_float(parts[1])
        if latitude is None or longitude is None:
            continue
        areas.append(
            GuardArea(
                latitude=latitude,
                longitude=longitude,
                radius_m=radius,
                name=name if isinstance(name, str) else None,
            )
        )
    return areas


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None

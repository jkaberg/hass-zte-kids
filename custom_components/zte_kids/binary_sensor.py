from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsCoordinatorEntity
from .sdk.models import GuardRule, haversine_m


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ZTEKidsSafeZone] = []
    for device_id in coordinator.data.devices:
        for rule in coordinator.guard_rules(device_id):
            entities.append(ZTEKidsSafeZone(coordinator, device_id, rule))
    async_add_entities(entities)


class ZTEKidsSafeZone(ZTEKidsCoordinatorEntity, BinarySensorEntity):
    """Whether the watch is inside one of its configured safe zones.

    The service only pushes enter and exit events, which a polling client never
    sees. Occupancy is therefore computed here from the watch's own reported
    position against the zone's centre and radius, which stays correct at any
    poll interval.
    """

    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(
        self,
        coordinator: ZTEKidsDataUpdateCoordinator,
        device_id: str,
        rule: GuardRule,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._rule_id = rule.rule_id
        self._attr_unique_id = f"{device_id}_zone_{rule.rule_id}"
        self._attr_name = rule.name or "Safe zone"
        self._attr_icon = "mdi:map-marker-check"

    @property
    def _rule(self) -> GuardRule | None:
        for rule in self.coordinator.guard_rules(self._device_id):
            if rule.rule_id == self._rule_id:
                return rule
        return None

    @property
    def available(self) -> bool:
        return super().available and self._rule is not None

    @property
    def is_on(self) -> bool | None:
        rule = self._rule
        location = self.device_snapshot.location
        if rule is None or location is None or not rule.areas:
            return None
        return rule.contains(location.latitude, location.longitude)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        rule = self._rule
        location = self.device_snapshot.location
        if rule is None:
            return None

        attributes: dict[str, Any] = {"enabled": rule.enabled}
        if location is not None and rule.areas:
            nearest = min(
                haversine_m(
                    location.latitude, location.longitude, area.latitude, area.longitude
                )
                - area.radius_m
                for area in rule.areas
            )
            attributes["distance_to_edge_m"] = round(nearest)
        return attributes

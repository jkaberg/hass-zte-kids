from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .entity import ZTEKidsCoordinatorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = entry.runtime_data
    async_add_entities(
        ZTEKidsDeviceTracker(runtime_data.coordinator, device_id)
        for device_id in runtime_data.coordinator.data.devices
    )


class ZTEKidsDeviceTracker(ZTEKidsCoordinatorEntity, TrackerEntity):
    _attr_name = None

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_location"

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        location = self.device_snapshot.location
        return None if location is None else location.latitude

    @property
    def longitude(self) -> float | None:
        location = self.device_snapshot.location
        return None if location is None else location.longitude

    @property
    def location_accuracy(self) -> int:
        location = self.device_snapshot.location
        if location is None or location.radius is None:
            return 0
        return location.radius

    @property
    def extra_state_attributes(self) -> dict[str, str | int] | None:
        location = self.device_snapshot.location
        if location is None:
            return None

        attributes: dict[str, str | int] = {}
        if location.address is not None:
            attributes["address"] = location.address
        if location.address_poi is not None:
            attributes["address_poi"] = location.address_poi
        if location.loc_type is not None:
            attributes["location_type"] = location.loc_type
        if location.timestamp is not None:
            attributes["location_timestamp"] = location.timestamp
        return attributes or None

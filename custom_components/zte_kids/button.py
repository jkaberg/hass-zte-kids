from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
        ZTEKidsForceRefreshButton(runtime_data.coordinator, device_id)
        for device_id in runtime_data.coordinator.data.devices
    )


class ZTEKidsForceRefreshButton(ZTEKidsCoordinatorEntity, ButtonEntity):
    _attr_icon = "mdi:crosshairs-gps"
    _attr_translation_key = "force_refresh"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_refresh_location"

    async def async_press(self) -> None:
        await self.coordinator.async_request_device_location_refresh(self._device_id)

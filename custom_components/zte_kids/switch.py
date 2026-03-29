from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
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
        ZTEKidsPollingEnabledSwitch(runtime_data.coordinator, device_id)
        for device_id in runtime_data.coordinator.data.devices
    )


class ZTEKidsPollingEnabledSwitch(ZTEKidsCoordinatorEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "polling_enabled"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_polling_enabled"

    @property
    def is_on(self) -> bool:
        return self.coordinator.device_polling_enabled(self._device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_device_polling_enabled(self._device_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_device_polling_enabled(self._device_id, False)
        self.async_write_ha_state()
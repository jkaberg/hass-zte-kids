from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .const import DEVICE_POLLING_INTERVAL_MAX_SECONDS, DEVICE_POLLING_INTERVAL_MIN_SECONDS
from .entity import ZTEKidsCoordinatorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = entry.runtime_data
    async_add_entities(
        ZTEKidsPollingIntervalNumber(runtime_data.coordinator, device_id)
        for device_id in runtime_data.coordinator.data.devices
    )


class ZTEKidsPollingIntervalNumber(ZTEKidsCoordinatorEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_max_value = DEVICE_POLLING_INTERVAL_MAX_SECONDS / 60
    _attr_native_min_value = DEVICE_POLLING_INTERVAL_MIN_SECONDS / 60
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_translation_key = "polling_interval"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_polling_interval"

    @property
    def native_value(self) -> float:
        return self.coordinator.device_polling_interval(self._device_id) / 60

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_device_polling_interval(self._device_id, int(value * 60))
        self.async_write_ha_state()
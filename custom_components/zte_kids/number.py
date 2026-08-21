from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .const import (
    DEVICE_POLLING_INTERVAL_MAX_SECONDS,
    DEVICE_POLLING_INTERVAL_MIN_SECONDS,
    STEP_GOAL_MAX,
    STEP_GOAL_MIN,
)
from .entity import ZTEKidsCoordinatorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[NumberEntity] = []
    for device_id in coordinator.data.devices:
        entities.append(ZTEKidsPollingIntervalNumber(coordinator, device_id))
        if coordinator.device_capabilities(device_id).supports("step"):
            entities.append(ZTEKidsStepGoalNumber(coordinator, device_id))
    async_add_entities(entities)


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

class ZTEKidsStepGoalNumber(ZTEKidsCoordinatorEntity, NumberEntity):
    """The watch's daily step target."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = STEP_GOAL_MIN
    _attr_native_max_value = STEP_GOAL_MAX
    _attr_native_step = 500
    _attr_icon = "mdi:target"
    _attr_translation_key = "step_goal"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_step_goal"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.sport_summary(self._device_id).goal

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_step_goal(self._device_id, int(value))

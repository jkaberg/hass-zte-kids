from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .entity import ZTEKidsCoordinatorEntity


@dataclass(frozen=True, slots=True)
class ZTEKidsSensorDescription(SensorEntityDescription):
    value_key: str = ""


SENSORS: tuple[ZTEKidsSensorDescription, ...] = (
    ZTEKidsSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="battery",
    ),
    ZTEKidsSensorDescription(
        key="steps",
        translation_key="steps",
        state_class=SensorStateClass.TOTAL,
        value_key="steps",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = entry.runtime_data
    entities: list[ZTEKidsSensor] = []
    for device_id in runtime_data.coordinator.data.devices:
        for description in SENSORS:
            entities.append(ZTEKidsSensor(runtime_data.coordinator, device_id, description))
    async_add_entities(entities)


class ZTEKidsSensor(ZTEKidsCoordinatorEntity, SensorEntity):
    entity_description: ZTEKidsSensorDescription

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: ZTEKidsSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self):
        return getattr(self.device_snapshot, self.entity_description.value_key)

    @property
    def extra_state_attributes(self):
        if self.entity_description.key != "battery":
            return None

        if self.device_snapshot.battery_timestamp is None:
            return None

        return {"updated_at": self.device_snapshot.battery_timestamp}

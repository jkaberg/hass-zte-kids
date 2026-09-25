from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength
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
    ZTEKidsSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_key="distance_m",
    ),
    ZTEKidsSensorDescription(
        key="calories",
        translation_key="calories",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kcal",
        suggested_display_precision=0,
        value_key="calories",
    ),
    ZTEKidsSensorDescription(
        key="unread_messages",
        translation_key="unread_messages",
        icon="mdi:message-badge",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="unread",
    ),
    ZTEKidsSensorDescription(
        key="location_updated",
        translation_key="location_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="location_timestamp",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = []
    for device_id in coordinator.data.devices:
        for description in SENSORS:
            entities.append(ZTEKidsSensor(coordinator, device_id, description))
        entities.append(ZTEKidsSosNumbersSensor(coordinator, device_id))
        entities.append(ZTEKidsPermissionsSensor(coordinator, device_id))
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
        key = self.entity_description.key
        if key == "location_updated":
            return _as_datetime(self.device_snapshot)
        if key in {"distance", "calories"}:
            summary = self.coordinator.sport_summary(self._device_id)
            return getattr(summary, self.entity_description.value_key)
        if key == "unread_messages":
            return self.coordinator.data.unread.get(self._device_id)
        return getattr(self.device_snapshot, self.entity_description.value_key)

    @property
    def extra_state_attributes(self):
        if self.entity_description.key != "battery":
            return None

        if self.device_snapshot.battery_timestamp is None:
            return None

        return {"updated_at": self.device_snapshot.battery_timestamp}


def _as_datetime(snapshot) -> datetime | None:
    """When the watch last reported a position.

    Timestamps arrive in either seconds or milliseconds depending on the
    endpoint that produced them, so the magnitude decides the unit.
    """
    location = snapshot.location
    if location is None or location.timestamp is None:
        return None
    timestamp = location.timestamp
    if timestamp > 1_000_000_000_000:
        timestamp = timestamp / 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


class ZTEKidsSosNumbersSensor(ZTEKidsCoordinatorEntity, SensorEntity):
    """The SOS numbers currently stored on the watch.

    These are written by `zte_kids.set_sos_numbers`, which replaces all three
    at once. Without somewhere to read them first, setting one means guessing
    at the other two — so this exists to be looked at before writing.
    """

    _attr_translation_key = "sos_numbers"
    _attr_icon = "mdi:phone-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_sos_numbers"

    @property
    def native_value(self) -> int:
        return sum(1 for number in self.device_config.sos.numbers if number)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        numbers = self.device_config.sos.numbers
        return {
            "number_1": numbers[0] or None,
            "number_2": numbers[1] or None,
            "number_3": numbers[2] or None,
        }


class ZTEKidsPermissionsSensor(ZTEKidsCoordinatorEntity, SensorEntity):
    """Which of the watch's internal features are switched on.

    The companion read for `zte_kids.set_permissions`, for the same reason.
    """

    _attr_translation_key = "permissions"
    _attr_icon = "mdi:shield-account"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_permissions"

    def _values(self) -> dict[str, bool | None]:
        config = self.device_config
        return {
            "location": config.position_permission,
            "battery": config.battery_permission,
            "sms": config.sms_permission,
            "activity": config.sports_permission,
            "apps": config.app_permission,
        }

    @property
    def native_value(self) -> int:
        return sum(1 for value in self._values().values() if value)

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        # Keyed exactly as the service's fields, so what you read is what you write.
        return self._values()

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsOptimisticEntity
from .sdk import commands
from .sdk.commands import LOCATION_MODE_OPTIONS, CommandType, LocationMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        ZTEKidsLocationModeSelect(coordinator, device_id)
        for device_id in coordinator.data.devices
    )


class ZTEKidsLocationModeSelect(ZTEKidsOptimisticEntity, SelectEntity):
    """How aggressively the watch fixes its position.

    Precision costs the most battery, power saving the least.
    """

    _attr_translation_key = "location_mode"
    _attr_icon = "mdi:map-marker-radius"
    _attr_options = list(LOCATION_MODE_OPTIONS)

    def __init__(self, coordinator: ZTEKidsDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_location_mode"

    @property
    def current_option(self) -> str | None:
        if self._optimistic is not None:
            return self._optimistic
        value = self.device_config.location_mode
        if value is None:
            return None
        for option, mode in LOCATION_MODE_OPTIONS.items():
            if mode == value:
                return option
        # An unrecognised mode is reported as unknown rather than guessed at.
        return None

    async def async_select_option(self, option: str) -> None:
        mode: LocationMode = LOCATION_MODE_OPTIONS[option]
        await self._async_send(
            commands.mode(CommandType.LOCATION_MODE, mode),
            refresh=True,
            cooldown=False,
        )
        self._apply_optimistic(option)

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsCoordinatorEntity
from .sdk import commands


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        ZTEKidsFirmwareUpdate(coordinator, device_id)
        for device_id in coordinator.data.devices
    )


class ZTEKidsFirmwareUpdate(ZTEKidsCoordinatorEntity, UpdateEntity):
    """Firmware on the watch.

    Installing tells the watch to start upgrading; it downloads and applies the
    build on its own schedule, so there is no progress to report back.
    """

    _attr_translation_key = "firmware"
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: ZTEKidsDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_firmware"

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.firmware(self._device_id).installed

    @property
    def latest_version(self) -> str | None:
        firmware = self.coordinator.firmware(self._device_id)
        # With nothing newer on offer, report the installed build so the entity
        # reads "up to date" rather than "unknown".
        return firmware.latest or firmware.installed

    def release_notes(self) -> str | None:
        return self.coordinator.firmware(self._device_id).release_notes

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        file_size = self.coordinator.firmware(self._device_id).file_size
        return {"file_size": file_size} if file_size else None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        await self._async_send(commands.START_FIRMWARE_UPGRADE)

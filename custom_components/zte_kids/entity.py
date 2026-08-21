from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZTEKidsDataUpdateCoordinator
from .sdk.commands import Command
from .sdk.models import Device, DeviceCapabilities, DeviceConfig, DeviceSnapshot


class ZTEKidsCoordinatorEntity(CoordinatorEntity[ZTEKidsDataUpdateCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ZTEKidsDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def available(self) -> bool:
        """Whether the watch is still present in the account.

        A watch can disappear from the device list — unbound elsewhere, or a
        partial API response — and entities must go unavailable rather than
        raise while reading state.
        """
        return (
            super().available
            and self.coordinator.data is not None
            and self._device_id in self.coordinator.data.devices
        )

    @property
    def device_snapshot(self) -> DeviceSnapshot:
        return self.coordinator.data.devices[self._device_id]

    @property
    def device(self) -> Device:
        return self.coordinator.get_device(self._device_id) or self.device_snapshot.device

    @property
    def capabilities(self) -> DeviceCapabilities:
        return self.coordinator.device_capabilities(self._device_id)

    @property
    def device_config(self) -> DeviceConfig:
        return self.coordinator.device_config(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="ZTE / Nubia",
            model=device.model,
            name=device.name or self._device_id,
            serial_number=self._device_id,
        )

    async def _async_send(
        self,
        command: Command,
        *,
        refresh: bool = False,
        cooldown: bool = True,
    ) -> None:
        await self.coordinator.async_send_command(
            self._device_id, command, refresh=refresh, cooldown=cooldown
        )


class ZTEKidsOptimisticEntity(ZTEKidsCoordinatorEntity):
    """A writable setting that shows the requested value until the watch confirms.

    Reading a setting back immediately after writing it tends to return the
    old value, so the entity would visibly snap back. The requested value is
    held until the next coordinator update, after which the entity always
    shows what the service actually reports — a write that silently failed
    surfaces rather than being papered over.
    """

    _optimistic: Any = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    def _apply_optimistic(self, value: Any) -> None:
        self._optimistic = value
        self.async_write_ha_state()

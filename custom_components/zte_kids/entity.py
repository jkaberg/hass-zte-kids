from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZTEKidsDataUpdateCoordinator
from .sdk.models import Device
from .sdk.models import DeviceSnapshot


class ZTEKidsCoordinatorEntity(CoordinatorEntity[ZTEKidsDataUpdateCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ZTEKidsDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def device_snapshot(self) -> DeviceSnapshot:
        return self.coordinator.data.devices[self._device_id]

    @property
    def device(self) -> Device:
        return self.coordinator.get_device(self._device_id) or self.device_snapshot.device

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="ZTE / Nubia",
            model=device.model,
            name=device.name or self._device_id,
        )

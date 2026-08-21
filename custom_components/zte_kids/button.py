from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsCoordinatorEntity
from .sdk import commands


@dataclass(frozen=True, kw_only=True)
class ZTEKidsButtonDescription(ButtonEntityDescription):
    """A watch action.

    ``capability`` names the ``support_*`` flag that must be advertised for the
    button to be created; ``None`` means the action is not capability-gated.
    """

    press_fn: Callable[[ZTEKidsDataUpdateCoordinator, str], Coroutine[Any, Any, None]]
    capability: str | None = None
    enabled_default: bool = True


BUTTONS: tuple[ZTEKidsButtonDescription, ...] = (
    ZTEKidsButtonDescription(
        key="refresh_location",
        translation_key="force_refresh",
        icon="mdi:crosshairs-gps",
        press_fn=lambda coordinator, device_id: (
            coordinator.async_request_device_location_refresh(device_id)
        ),
    ),
    ZTEKidsButtonDescription(
        key="refresh_data",
        translation_key="refresh_data",
        icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda coordinator, device_id: coordinator.async_refresh_device(device_id),
    ),
    ZTEKidsButtonDescription(
        key="find_watch",
        translation_key="find_watch",
        icon="mdi:bell-ring",
        capability="find",
        press_fn=lambda coordinator, device_id: coordinator.async_send_command(
            device_id, commands.FIND_WATCH
        ),
    ),
    ZTEKidsButtonDescription(
        key="restart",
        translation_key="restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator, device_id: coordinator.async_send_command(
            device_id, commands.RESTART
        ),
    ),
    ZTEKidsButtonDescription(
        key="power_off",
        translation_key="power_off",
        icon="mdi:power",
        entity_category=EntityCategory.CONFIG,
        # A powered-off watch can only be switched back on by hand, so this is
        # opt-in: enabling it is the confirmation step that a button press
        # itself cannot provide.
        enabled_default=False,
        press_fn=lambda coordinator, device_id: coordinator.async_send_command(
            device_id, commands.POWER_OFF
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[ZTEKidsButton] = []
    for device_id in coordinator.data.devices:
        capabilities = coordinator.device_capabilities(device_id)
        for description in BUTTONS:
            # A watch that does not advertise a feature usually cannot do it,
            # but the flag is not proof: the app gates features on the model
            # and the account's permissions too, and some models report 0 for
            # things they support. So the entity is created either way and
            # simply starts disabled, which is diagnosable. Silently creating
            # nothing is not.
            supported = not description.capability or capabilities.supports(
                description.capability
            )
            entities.append(
                ZTEKidsButton(
                    coordinator,
                    device_id,
                    description,
                    enabled_default=supported and description.enabled_default,
                )
            )
    async_add_entities(entities)


class ZTEKidsButton(ZTEKidsCoordinatorEntity, ButtonEntity):
    entity_description: ZTEKidsButtonDescription

    def __init__(
        self,
        coordinator: ZTEKidsDataUpdateCoordinator,
        device_id: str,
        description: ZTEKidsButtonDescription,
        *,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_entity_registry_enabled_default = enabled_default

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator, self._device_id)

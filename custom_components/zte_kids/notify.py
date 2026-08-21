from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .const import DOMAIN, MAX_MESSAGE_LENGTH
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsCoordinatorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        # Created even when the watch does not advertise chat, because the flag
        # is not proof — it just starts disabled. See the note in button.py.
        ZTEKidsNotify(
            coordinator,
            device_id,
            enabled_default=coordinator.device_capabilities(device_id).supports("chat"),
        )
        for device_id in coordinator.data.devices
    )


class ZTEKidsNotify(ZTEKidsCoordinatorEntity, NotifyEntity):
    """Sends a chat message to the watch, where the child reads it."""

    _attr_translation_key = "message"
    _attr_icon = "mdi:message-text"

    def __init__(
        self,
        coordinator: ZTEKidsDataUpdateCoordinator,
        device_id: str,
        *,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_message"
        self._attr_entity_registry_enabled_default = enabled_default

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        text = message.strip()
        if not text:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="empty_message",
            )
        if len(text) > MAX_MESSAGE_LENGTH:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="message_too_long",
                translation_placeholders={
                    "length": str(len(text)),
                    "maximum": str(MAX_MESSAGE_LENGTH),
                },
            )
        await self.coordinator.async_send_message(self._device_id, text)

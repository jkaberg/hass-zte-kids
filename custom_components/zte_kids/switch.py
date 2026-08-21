from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZTEKidsConfigEntry
from .coordinator import ZTEKidsDataUpdateCoordinator
from .entity import ZTEKidsCoordinatorEntity, ZTEKidsOptimisticEntity
from .sdk import commands
from .sdk.commands import CommandType


@dataclass(frozen=True, kw_only=True)
class ZTEKidsSwitchDescription(SwitchEntityDescription):
    """A two-state watch setting.

    ``config_attr`` is the :class:`DeviceConfig` field the current value is
    read from; ``command_type`` is the command that writes it.
    """

    command_type: CommandType
    config_attr: str
    capability: str | None = None
    write_fn: (
        Callable[[ZTEKidsDataUpdateCoordinator, str, bool], Coroutine[Any, Any, None]] | None
    ) = None


SWITCHES: tuple[ZTEKidsSwitchDescription, ...] = (
    ZTEKidsSwitchDescription(
        key="battery_saver",
        translation_key="battery_saver",
        icon="mdi:battery-heart-variant",
        command_type=CommandType.LONG_LIFE_MODE,
        config_attr="long_life_mode",
    ),
    ZTEKidsSwitchDescription(
        key="auto_answer",
        translation_key="auto_answer",
        icon="mdi:phone-in-talk",
        command_type=CommandType.AUTO_ANSWER,
        config_attr="auto_answer",
        capability="call_phone",
    ),
    ZTEKidsSwitchDescription(
        key="call_whitelist",
        translation_key="call_whitelist",
        icon="mdi:phone-lock",
        command_type=CommandType.CALL_WHITELIST,
        config_attr="call_whitelist",
        capability="white_list",
    ),
    ZTEKidsSwitchDescription(
        key="sms_receive",
        translation_key="sms_receive",
        icon="mdi:message-processing",
        command_type=CommandType.SMS_RECEIVE,
        config_attr="sms_receive",
    ),
    ZTEKidsSwitchDescription(
        key="sms_members_only",
        translation_key="sms_members_only",
        icon="mdi:account-lock",
        command_type=CommandType.SMS_MEMBERS_ONLY,
        config_attr="sms_members_only",
    ),
    ZTEKidsSwitchDescription(
        key="scheduled_power_off",
        translation_key="scheduled_power_off",
        icon="mdi:timer-off",
        command_type=CommandType.SCHEDULED_POWER_OFF,
        config_attr="scheduled_power_off",
        capability="timing_switch",
        write_fn=lambda coordinator, device_id, value: (
            coordinator.async_set_scheduled_power_off(device_id, enabled=value)
        ),
    ),
    ZTEKidsSwitchDescription(
        key="shutdown_protection",
        translation_key="shutdown_protection",
        icon="mdi:shield-lock",
        entity_category=EntityCategory.CONFIG,
        command_type=CommandType.SHUTDOWN_PROTECTION,
        config_attr="shutdown_protection_enabled",
        write_fn=lambda coordinator, device_id, value: (
            coordinator.async_set_shutdown_protection(device_id, enabled=value)
        ),
    ),
    ZTEKidsSwitchDescription(
        key="task_reminder",
        translation_key="task_reminder",
        icon="mdi:clipboard-check",
        command_type=CommandType.TASK_REMINDER,
        config_attr="task_reminder_enabled",
        write_fn=lambda coordinator, device_id, value: (
            coordinator.async_set_task_reminder(device_id, enabled=value)
        ),
    ),
)

# Do-not-disturb (type 6) is deliberately absent. Its state is not a scalar in
# ConfigData - it lives only in the `disBan` rule list - so a switch could
# write it but never report it. A control that cannot show its own state is
# worse than no control.

# The watch's internal feature permissions are not here either. They are five
# separate wire commands that are almost always changed together and almost
# never changed at all, so they are the `zte_kids.set_permissions` action.


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZTEKidsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SwitchEntity] = []
    for device_id in coordinator.data.devices:
        entities.append(ZTEKidsPollingEnabledSwitch(coordinator, device_id))

        capabilities = coordinator.device_capabilities(device_id)
        for description in SWITCHES:
            if description.capability and not capabilities.supports(description.capability):
                continue
            entities.append(ZTEKidsConfigSwitch(coordinator, device_id, description))
    async_add_entities(entities)


class ZTEKidsPollingEnabledSwitch(ZTEKidsCoordinatorEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "polling_enabled"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_polling_enabled"

    @property
    def is_on(self) -> bool:
        return self.coordinator.device_polling_enabled(self._device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_device_polling_enabled(self._device_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_device_polling_enabled(self._device_id, False)
        self.async_write_ha_state()


class ZTEKidsConfigSwitch(ZTEKidsOptimisticEntity, SwitchEntity):
    """A setting stored on the watch itself."""

    entity_description: ZTEKidsSwitchDescription

    def __init__(
        self,
        coordinator: ZTEKidsDataUpdateCoordinator,
        device_id: str,
        description: ZTEKidsSwitchDescription,
        *,
        entity_category: EntityCategory | None = None,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        if entity_category is not None:
            self._attr_entity_category = entity_category
        self._attr_entity_registry_enabled_default = enabled_default

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        return _config_value(self.device_config, self.entity_description.config_attr)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)

    async def _async_write(self, value: bool) -> None:
        description = self.entity_description
        if description.write_fn is not None:
            await description.write_fn(self.coordinator, self._device_id, value)
        else:
            await self._async_send(
                commands.switch(description.command_type, value),
                refresh=True,
                cooldown=False,
            )
        self._apply_optimistic(value)


def _config_value(config, attr: str) -> bool | None:
    if attr == "shutdown_protection_enabled":
        return config.shutdown_protection.enabled
    if attr == "task_reminder_enabled":
        return config.task_reminder.enabled
    return getattr(config, attr, None)

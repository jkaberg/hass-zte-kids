from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.httpx_client import get_async_client

from .coordinator import ZTEKidsDataUpdateCoordinator
from .sdk import ZTEKidsClient

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .coordinator import ZTEKidsDataUpdateCoordinator
    from .sdk import ZTEKidsClient


@dataclass(slots=True)
class RuntimeData:
    client: ZTEKidsClient
    coordinator: ZTEKidsDataUpdateCoordinator


if TYPE_CHECKING:
    ZTEKidsConfigEntry = ConfigEntry[RuntimeData]
else:
    ZTEKidsConfigEntry = Any


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ZTEKidsConfigEntry) -> bool:
    from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME

    from .const import PLATFORMS
    from .sdk import Environment
    from .sdk.models import Credentials

    entry_data = dict(entry.data)
    if CONF_SCAN_INTERVAL in entry_data:
        entry_data.pop(CONF_SCAN_INTERVAL)
        hass.config_entries.async_update_entry(entry, data=entry_data)

    client = ZTEKidsClient(
        environment=Environment.PRODUCTION,
        http_client=get_async_client(hass),
        close_http_client=False,
    )
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(
            username=entry_data[CONF_USERNAME],
            password=entry_data[CONF_PASSWORD],
        ),
        config_entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = RuntimeData(client=client, coordinator=coordinator)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown()
        await client.aclose()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZTEKidsConfigEntry) -> bool:
    from .const import PLATFORMS

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    runtime_data = entry.runtime_data
    await runtime_data.coordinator.async_shutdown()
    await runtime_data.client.aclose()
    return True

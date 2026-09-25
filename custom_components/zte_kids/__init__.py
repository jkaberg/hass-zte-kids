from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.httpx_client import get_async_client

from .const import DOMAIN
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
    push: Any = None
    #: The push setting as last applied, so an options change can be told
    #: apart from a save that left it alone.
    push_enabled: bool = False


if TYPE_CHECKING:
    ZTEKidsConfigEntry = ConfigEntry[RuntimeData]
else:
    ZTEKidsConfigEntry = Any


LOGGER = logging.getLogger(__name__)

LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .services import async_register_services

    async_register_services(hass)
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

    from .services import async_register_services

    async_register_services(hass)

    entry.runtime_data = RuntimeData(client=client, coordinator=coordinator)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown()
        await client.aclose()
        raise

    await _async_start_push(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_start_push(hass: HomeAssistant, entry: ZTEKidsConfigEntry) -> None:
    """Open the real-time event stream, if it is turned on.

    Push is strictly additive and off by default. A broker that refuses us or
    has gone away leaves the integration exactly as it was, polling over HTTP.
    """
    from .const import CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH

    enabled = entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH)
    entry.runtime_data.push_enabled = enabled
    if not enabled:
        return

    from .push import ZTEKidsPushManager

    manager = ZTEKidsPushManager(hass, entry.runtime_data.coordinator)
    try:
        await manager.async_start()
    except Exception as err:
        LOGGER.warning(
            "Could not open the ZTE Kids event stream; continuing with polling: %s",
            err,
        )
        return

    entry.runtime_data.push = manager


async def _async_options_updated(hass: HomeAssistant, entry: ZTEKidsConfigEntry) -> None:
    """Apply changed options in place instead of rebuilding the entry.

    The polling number and switch write their setting straight into the entry
    options, so reloading here would take every entity unavailable for the
    length of a full setup - a fresh login included - to land a change the
    coordinator can apply live. Only the event stream owns anything that has
    to be built or torn down, and it can be started and stopped on its own.
    """
    from .const import CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH

    runtime_data = entry.runtime_data
    runtime_data.coordinator.async_options_updated()

    enabled = entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH)
    if enabled == runtime_data.push_enabled:
        # Only the polling settings moved. Deliberately not a reconnect hook:
        # a stream that failed to open is paho's to retry, not something a
        # nudge of the polling interval should go and poke.
        return

    if enabled:
        await _async_start_push(hass, entry)
        return

    runtime_data.push_enabled = False
    if runtime_data.push is not None:
        await runtime_data.push.async_stop()
        runtime_data.push = None
        runtime_data.coordinator.async_set_push_connected(False)


async def async_unload_entry(hass: HomeAssistant, entry: ZTEKidsConfigEntry) -> bool:
    from .const import PLATFORMS

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    runtime_data = entry.runtime_data
    if runtime_data.push is not None:
        await runtime_data.push.async_stop()
        runtime_data.push = None
    await runtime_data.coordinator.async_shutdown()
    await runtime_data.client.aclose()
    return True

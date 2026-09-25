"""The actions that replaced per-field configuration entities.

The point of these is atomicity: one call, one write, no intermediate state on
the watch. The regression these guard against is the one the entity model had
— a script setting three related fields producing three partial writes, two of
which were rejected by the command cooldown.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.helpers import device_registry as dr
import pytest
from test_entity_setup import _client, _setup

from custom_components.zte_kids.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _device_id(hass) -> str:
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, "imei-1")})
    assert device is not None
    return device.id


@pytest.mark.asyncio
async def test_setting_all_three_sos_numbers_is_one_write(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_sos_numbers",
        {
            "device_id": _device_id(hass),
            "number_1": "111",
            "number_2": "222",
            "number_3": "333",
        },
        blocking=True,
    )

    assert client.configuration.send_command.await_count == 1
    _, _, command = client.configuration.send_command.await_args.args
    assert command.body("imei-1") == {
        "deviceId": "imei-1",
        "type": 12,
        "sos": {"sos1": "111", "sos2": "222", "sos3": "333"},
    }

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_omitted_sos_numbers_keep_their_current_value(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_sos_numbers",
        {"device_id": _device_id(hass), "number_2": "999"},
        blocking=True,
    )

    _, _, command = client.configuration.send_command.await_args.args
    # sos1 came from the watch's current config, sos3 was empty there.
    assert command.body("imei-1")["sos"] == {
        "sos1": "111",
        "sos2": "999",
        "sos3": "",
    }

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_power_off_window_is_set_in_one_write(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_power_off_schedule",
        {
            "device_id": _device_id(hass),
            "enabled": True,
            "start_time": "23:15:00",
            "end_time": "07:00:00",
        },
        blocking=True,
    )

    assert client.configuration.send_command.await_count == 1
    _, _, command = client.configuration.send_command.await_args.args
    assert command.body("imei-1") == {
        "deviceId": "imei-1",
        "type": 19,
        "status": 1,
        "rule": {"interval": {"startTime": "23:15", "endTime": "07:00"}},
    }

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_shutdown_protection_sets_switch_and_password_together(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_shutdown_protection",
        {"device_id": _device_id(hass), "enabled": True, "password": "4321"},
        blocking=True,
    )

    assert client.configuration.send_command.await_count == 1
    _, _, command = client.configuration.send_command.await_args.args
    assert command.body("imei-1")["shutdownVo"] == {
        "status": 1,
        "shutdownPwd": "4321",
    }

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_task_reminder_sets_switch_and_time_together(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_task_reminder",
        {"device_id": _device_id(hass), "enabled": True, "time": "18:30"},
        blocking=True,
    )

    _, _, command = client.configuration.send_command.await_args.args
    assert command.body("imei-1")["taskReminderVO"] == {
        "reminderStatus": 1,
        "reminderTime": "18:30",
    }

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_permissions_send_one_command_each_without_hitting_the_cooldown(
    hass,
) -> None:
    """These really are separate wire commands, so a loop is correct here.

    What must not happen is the command cooldown rejecting the later ones.
    """
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        DOMAIN,
        "set_permissions",
        {
            "device_id": _device_id(hass),
            "location": True,
            "battery": True,
            "sms": False,
            "activity": True,
            "apps": False,
        },
        blocking=True,
    )

    assert client.configuration.send_command.await_count == 5
    types = {
        int(call.args[2].command_type)
        for call in client.configuration.send_command.await_args_list
    }
    assert types == {14, 15, 16, 17, 18}

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_an_unknown_device_target_is_rejected_clearly(hass) -> None:
    from homeassistant.exceptions import HomeAssistantError

    client = _client()
    entry = await _setup(hass, client)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_sos_numbers",
            {"device_id": "not-a-device", "number_1": "111"},
            blocking=True,
        )
    assert err.value.translation_key == "unknown_device"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

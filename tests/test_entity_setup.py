"""End-to-end platform setup: the entities a real account would produce."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import DOMAIN
from custom_components.zte_kids.sdk.models import (
    AccountProfile,
    ChatSession,
    Device,
    Session,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

DEVICE_PAYLOAD = {
    "imei": "imei-1",
    "name": "Watch 1",
    "model": "W2020",
    "openid": "openid",
    "groupid": "group-1",
    "isAdmin": True,
    "battery": {"percent": 64, "updateTime": 1700000000},
    "step_num": 4212,
    "lastLocation": {"lat": 59.9148, "lon": 10.7522, "radius": 30, "timestamp": 1700000000},
    "support_find": 1,
    "support_chat": 1,
    "support_step": 1,
    "support_sos": 1,
    "support_timingSwitch": 1,
    "support_whiteList": 1,
    "support_callPhone": 1,
}


CONFIG_PAYLOAD = {
    "imei": "imei-1",
    "locMode": 2,
    "longLifeMode": 1,
    "callWhitelist": 2,
    "autoAnswer": 1,
    "sms": 1,
    "smsReceiveOnlyMember": 2,
    "positionSwitch": 1,
    "batterySwitch": 1,
    "smsSwitch": 1,
    "sportsSwitch": 1,
    "appSwitch": 2,
    "bootOffSwitch": 1,
    "bootOffStartTime": "22:00",
    "bootOffEndTime": "06:30",
    "shutdownVO": {"status": 1, "shutdownPwd": "1234"},
    "taskReminderVO": {"reminderStatus": 1, "reminderTime": "17:00"},
    "sos": {"sos1": "111", "sos2": "222", "sos3": ""},
    "battery": {"percent": 64},
}


SPORT_ROWS = [
    {"hour": 8, "step": 900, "day": "2026-08-21"},
    {
        "hour": 14,
        "totalStep": 4212,
        "totalDistance": 3100.5,
        "totalCalorie": 182.4,
        "day": "2026-08-21",
    },
]

FIRMWARE_PAYLOAD = {
    "deviceFirmware": "W2020_1.0.3",
    "firmware": "W2020_1.0.5",
    "releaseNote": "Battery fixes",
    "fileSize": "12MB",
}

# Oslo city centre, 200 m radius. `coordinate` is "lon,lat".
GUARD_RULES = [
    {
        "securityGuardId": "zone-1",
        "ruleName": "School",
        "status": 1,
        "addr": [{"coordinate": "10.7522,59.9139", "addrRange": 200, "addrName": "School"}],
    }
]


def _client() -> MagicMock:
    client = MagicMock()
    client.aclose = AsyncMock()
    client.configuration.get_system_config = AsyncMock(
        return_value=dict(CONFIG_PAYLOAD)
    )
    client.sport.query_daily = AsyncMock(return_value=list(SPORT_ROWS))
    client.sport.query_aim = AsyncMock(return_value={"aim": 9000})
    client.devices.query_firmware = AsyncMock(return_value=dict(FIRMWARE_PAYLOAD))
    client.guard.list_rules = AsyncMock(return_value=list(GUARD_RULES))
    client.messages.unread_counts = AsyncMock(
        return_value=[{"imei": "imei-1", "num": 3}]
    )
    client.auth.login = AsyncMock(
        return_value=Session(access_token="token", openid="openid")
    )
    client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    client.devices.list_related_devices = AsyncMock(
        return_value=[Device.from_payload(dict(DEVICE_PAYLOAD))]
    )
    return client


async def _setup(hass, client: MagicMock) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.zte_kids.ZTEKidsClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.mark.asyncio
async def test_setup_creates_the_expected_entities(hass) -> None:
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    unique_ids = {item.unique_id for item in entries}

    assert "imei-1_refresh_location" in unique_ids
    assert "imei-1_refresh_data" in unique_ids
    assert "imei-1_find_watch" in unique_ids
    assert "imei-1_restart" in unique_ids
    assert "imei-1_power_off" in unique_ids
    assert "imei-1_message" in unique_ids
    assert "imei-1_location_updated" in unique_ids

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_power_off_is_disabled_until_the_user_enables_it(hass) -> None:
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)

    power_off = next(
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id == "imei-1_power_off"
    )
    restart = next(
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id == "imei-1_restart"
    )

    assert power_off.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # Restarting is recoverable, so it does not need the same guard.
    assert restart.disabled_by is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_unadvertised_features_are_disabled_rather_than_missing(hass) -> None:
    """A `support_*` flag of 0 is not proof the watch cannot do it.

    The app gates features on the model and the account's permissions too, and
    real watches report 0 for things they support. An entity that exists but
    starts disabled can be enabled and diagnosed; one that was never created
    just looks like the integration is broken.
    """
    payload = dict(DEVICE_PAYLOAD)
    payload["support_find"] = 0
    payload["support_chat"] = 0
    client = _client()
    client.devices.list_related_devices = AsyncMock(
        return_value=[Device.from_payload(payload)]
    )

    entry = await _setup(hass, client)
    registry = er.async_get(hass)
    entries = {
        item.unique_id: item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    assert entries["imei-1_find_watch"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entries["imei-1_message"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # Actions that are not capability-gated are unaffected.
    assert entries["imei-1_restart"].disabled_by is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_find_watch_button_sends_the_command(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.watch_1_find_watch"},
        blocking=True,
    )

    client.configuration.send_command.assert_awaited_once()
    _, device_id, command = client.configuration.send_command.await_args.args
    assert device_id == "imei-1"
    assert int(command.command_type) == 4

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_notify_entity_sends_a_message(hass) -> None:
    client = _client()
    client.chat.list_sessions = AsyncMock(
        return_value=[
            ChatSession(
                chat_id="chat-1",
                chat_type=2,
                device_id="imei-1",
                group_id="group-1",
                recv_id="recv-1",
            )
        ]
    )
    client.chat.send_text = AsyncMock(return_value={"code": 0})
    entry = await _setup(hass, client)

    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.watch_1_message", "message": "home by six"},
        blocking=True,
    )

    client.chat.send_text.assert_awaited_once()
    assert client.chat.send_text.await_args.args[2] == "home by six"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_config_backed_entities_read_the_watch_settings(hass) -> None:
    entry = await _setup(hass, _client())

    assert hass.states.get("select.watch_1_location_mode").state == "normal"
    assert hass.states.get("switch.watch_1_battery_saver").state == "on"
    assert hass.states.get("switch.watch_1_call_whitelist").state == "off"
    assert hass.states.get("switch.watch_1_scheduled_power_off").state == "on"
    assert hass.states.get("switch.watch_1_task_reminder").state == "on"
    assert hass.states.get("switch.watch_1_shutdown_protection").state == "on"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_selecting_a_location_mode_sends_the_mode_command(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.watch_1_location_mode", "option": "power_saving"},
        blocking=True,
    )

    _, device_id, command = client.configuration.send_command.await_args.args
    assert device_id == "imei-1"
    assert command.body("imei-1") == {"deviceId": "imei-1", "type": 1, "mode": 3}

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_activity_and_firmware_entities(hass) -> None:
    entry = await _setup(hass, _client())

    assert hass.states.get("sensor.watch_1_distance_today").state == "3.1005"
    assert hass.states.get("sensor.watch_1_calories_today").state == "182.4"
    assert hass.states.get("sensor.watch_1_unread_messages").state == "3"
    assert hass.states.get("number.watch_1_step_goal").state == "9000"

    firmware = hass.states.get("update.watch_1_firmware")
    assert firmware.state == "on"  # an update is available
    assert firmware.attributes["installed_version"] == "W2020_1.0.3"
    assert firmware.attributes["latest_version"] == "W2020_1.0.5"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_safe_zone_occupancy_is_computed_locally(hass) -> None:
    """The watch sits on the zone centre, so it reads as present."""
    entry = await _setup(hass, _client())

    zone = hass.states.get("binary_sensor.watch_1_school")
    assert zone is not None
    assert zone.state == "on"
    assert zone.attributes["enabled"] is True
    # 100 m from the centre of a 200 m zone, so 100 m inside its edge.
    assert zone.attributes["distance_to_edge_m"] == -100

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_safe_zone_reads_off_when_the_watch_is_elsewhere(hass) -> None:
    payload = dict(DEVICE_PAYLOAD)
    payload["lastLocation"] = {
        "lat": 59.85,
        "lon": 10.60,
        "radius": 30,
        "timestamp": 1700000000,
    }
    client = _client()
    client.devices.list_related_devices = AsyncMock(
        return_value=[Device.from_payload(payload)]
    )

    entry = await _setup(hass, client)

    assert hass.states.get("binary_sensor.watch_1_school").state == "off"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_installing_firmware_sends_the_upgrade_command(hass) -> None:
    client = _client()
    client.configuration.send_command = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        "update",
        "install",
        {"entity_id": "update.watch_1_firmware"},
        blocking=True,
    )

    _, _, command = client.configuration.send_command.await_args.args
    assert command.body("imei-1") == {"deviceId": "imei-1", "type": 11}

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_setting_the_step_goal_calls_the_sport_api(hass) -> None:
    client = _client()
    client.sport.set_aim = AsyncMock()
    entry = await _setup(hass, client)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.watch_1_step_goal", "value": 12000},
        blocking=True,
    )

    client.sport.set_aim.assert_awaited_once()
    _, device_id, goal = client.sport.set_aim.await_args.args
    assert device_id == "imei-1"
    assert goal == 12000

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_sos_and_permissions_can_be_read_before_they_are_written(hass) -> None:
    """Both are written as a whole object, so they need somewhere to be read."""
    entry = await _setup(hass, _client())

    sos = hass.states.get("sensor.watch_1_sos_numbers_set")
    assert sos.state == "2"
    assert sos.attributes["number_1"] == "111"
    assert sos.attributes["number_2"] == "222"
    assert sos.attributes["number_3"] is None

    permissions = hass.states.get("sensor.watch_1_permissions_enabled")
    assert permissions.state == "4"
    assert permissions.attributes["location"] is True
    assert permissions.attributes["apps"] is False

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_toggling_polling_does_not_take_the_entities_away(hass) -> None:
    """Changing a polling setting must not reload the entry.

    The polling switch and number write into the entry options, so a listener
    that reloads on any options change turns a local setting into a full
    teardown: every entity drops to unavailable and the account is logged in
    again, for a change the coordinator can apply where it stands.
    """
    client = _client()
    entry = await _setup(hass, client)
    coordinator = entry.runtime_data.coordinator
    logins = client.auth.login.await_count

    states: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: states.append(event.data["new_state"].state)
        if event.data["entity_id"] == "sensor.watch_1_battery"
        and event.data["new_state"] is not None
        else None,
    )

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.watch_1_polling_enabled"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("switch.watch_1_polling_enabled").state == "off"
    assert "unavailable" not in states
    # Same coordinator, no second login: the entry was never rebuilt.
    assert entry.runtime_data.coordinator is coordinator
    assert client.auth.login.await_count == logins

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

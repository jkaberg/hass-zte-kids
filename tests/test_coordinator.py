from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import (
    CONF_DEVICE_POLLING,
    CONF_POLLING_ENABLED,
    CONF_POLLING_INTERVAL,
    DOMAIN,
)
from custom_components.zte_kids.coordinator import CoordinatorData, ZTEKidsDataUpdateCoordinator
from custom_components.zte_kids.number import ZTEKidsPollingIntervalNumber
from custom_components.zte_kids.sdk import SessionExpiredError
from custom_components.zte_kids.sdk.models import (
    AccountProfile,
    Credentials,
    Device,
    DeviceSnapshot,
    Session,
)


def _mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        },
    )


@pytest.mark.asyncio
async def test_session_expiry_raises_config_entry_auth_failed(hass) -> None:
    client = MagicMock()
    client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
    client.auth.query_profile = AsyncMock(
        side_effect=SessionExpiredError(code=1002, message="Session expired")
    )

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_mock_entry(),
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    assert coordinator._session is None


@pytest.mark.asyncio
async def test_update_data_uses_related_device_payload_for_snapshot(hass) -> None:
    client = MagicMock()
    client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
    client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    client.devices.list_related_devices = AsyncMock(
        return_value=[
            Device.from_payload(
                {
                    "imei": "imei-1",
                    "name": "Watch 1",
                    "groupid": "group-1",
                    "single_groupid": "single-1",
                    "model": "EW2406",
                    "step_num": 1610,
                    "battery": {"percent": 44, "updateTime": 1774801318667},
                    "lastLocation": {"lat": "59.9148", "lon": "10.7522", "radius": "11"},
                }
            )
        ]
    )

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_mock_entry(),
    )

    data = await coordinator._async_update_data()

    snapshot = data.devices["imei-1"]
    assert snapshot.steps == 1610
    assert snapshot.battery == 44
    assert snapshot.battery_timestamp == 1774801318667
    assert snapshot.location is not None
    assert snapshot.location.latitude == 59.9148
    assert snapshot.device.group_id == "group-1"
    assert snapshot.device.single_group_id == "single-1"


@pytest.mark.asyncio
async def test_cached_session_reuses_cached_profile_between_polls(hass) -> None:
    client = MagicMock()
    session = Session(access_token="token", openid="openid")
    client.auth.login = AsyncMock(return_value=session)
    client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    client.devices.list_related_devices = AsyncMock(
        side_effect=[
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 80}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 81}}
                )
            ],
        ]
    )

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_mock_entry(),
    )

    clock = {"now": 0.0}
    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_refresh()
        clock["now"] = 1801.0
        await coordinator.async_refresh()

    client.auth.login.assert_awaited_once()
    client.auth.query_profile.assert_awaited_once()
    assert coordinator.data.devices["imei-1"].battery == 81


@pytest.mark.asyncio
async def test_disabled_device_polling_preserves_existing_snapshot(hass) -> None:
    client = MagicMock()
    client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
    client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    client.devices.list_related_devices = AsyncMock(
        side_effect=[
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 80}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 10}}
                )
            ],
        ]
    )

    entry = _mock_entry()
    entry.add_to_hass(hass)

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=entry,
    )

    await coordinator.async_refresh()
    assert coordinator.data.devices["imei-1"].battery == 80

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {
                    CONF_POLLING_ENABLED: False,
                }
            }
        },
    )

    await coordinator.async_refresh()

    assert client.devices.list_related_devices.await_count == 2
    assert coordinator.data.devices["imei-1"].battery == 80


@pytest.mark.asyncio
async def test_force_refresh_bypasses_interval_gating(hass) -> None:
    client = MagicMock()
    session = Session(access_token="token", openid="openid")
    client.auth.login = AsyncMock(return_value=session)
    client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    client.devices.list_related_devices = AsyncMock(
        side_effect=[
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 10}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 20}}
                )
            ],
        ]
    )
    client.devices.request_location_refresh = AsyncMock(return_value={"code": 0})

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        },
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {
                    CONF_POLLING_INTERVAL: 3600,
                }
            }
        },
    )
    entry.add_to_hass(hass)

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=entry,
    )

    clock = {"now": 0.0}
    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_refresh()
        assert coordinator.data.devices["imei-1"].battery == 10
        clock["now"] = 60.0
        await coordinator.async_request_device_location_refresh("imei-1")

    assert client.devices.request_location_refresh.await_count == 1
    assert coordinator.data.devices["imei-1"].battery == 20
    await coordinator.async_shutdown()
    coordinator._debounced_refresh.async_cancel()


def test_polling_interval_number_uses_minutes(hass) -> None:
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=MagicMock(),
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_mock_entry(),
    )
    data = CoordinatorData(
        session=Session(access_token="token", openid="openid"),
        profile=AccountProfile(openid="openid"),
        devices={
            "imei-1": DeviceSnapshot(
                device=Device(device_id="imei-1", name="Watch 1"),
                raw={"imei": "imei-1", "name": "Watch 1"},
            )
        },
    )
    coordinator.async_set_updated_data(data)
    coordinator._latest_data = data

    entity = ZTEKidsPollingIntervalNumber(coordinator, "imei-1")

    assert entity.native_value == 30


@pytest.mark.asyncio
async def test_polling_interval_number_saves_five_minutes(hass) -> None:
    entry = _mock_entry()
    entry.add_to_hass(hass)

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=MagicMock(),
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=entry,
    )
    data = CoordinatorData(
        session=Session(access_token="token", openid="openid"),
        profile=AccountProfile(openid="openid"),
        devices={
            "imei-1": DeviceSnapshot(
                device=Device(device_id="imei-1", name="Watch 1"),
                raw={"imei": "imei-1", "name": "Watch 1"},
            )
        },
    )
    coordinator.async_set_updated_data(data)
    coordinator._latest_data = data
    coordinator.async_request_refresh = AsyncMock()

    entity = ZTEKidsPollingIntervalNumber(coordinator, "imei-1")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(5)

    assert coordinator.device_polling_interval("imei-1") == 300
    assert entry.options[CONF_DEVICE_POLLING]["imei-1"][CONF_POLLING_INTERVAL] == 300
    coordinator._debounced_refresh.async_cancel()


async def test_coordinator_update_interval_uses_device_polling_inputs(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        },
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {CONF_POLLING_INTERVAL: 1800},
                "imei-2": {CONF_POLLING_INTERVAL: 3600},
            }
        },
    )
    entry.add_to_hass(hass)

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=MagicMock(),
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=entry,
    )
    coordinator._device_catalog = {
        "imei-1": Device(device_id="imei-1", name="Watch 1"),
        "imei-2": Device(device_id="imei-2", name="Watch 2"),
    }

    coordinator._update_polling_interval()
    assert coordinator.update_interval == timedelta(seconds=1800)

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {
                    CONF_POLLING_ENABLED: False,
                    CONF_POLLING_INTERVAL: 1800,
                },
                "imei-2": {CONF_POLLING_INTERVAL: 3600},
            }
        },
    )
    coordinator._update_polling_interval()
    assert coordinator.update_interval == timedelta(seconds=3600)

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {
                    CONF_POLLING_ENABLED: False,
                    CONF_POLLING_INTERVAL: 1800,
                },
                "imei-2": {
                    CONF_POLLING_ENABLED: False,
                    CONF_POLLING_INTERVAL: 3600,
                },
            }
        },
    )
    coordinator._update_polling_interval()
    assert coordinator.update_interval is None

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.button import BUTTONS, ZTEKidsButton
from custom_components.zte_kids.const import DOMAIN
from custom_components.zte_kids.coordinator import CoordinatorData, ZTEKidsDataUpdateCoordinator
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
async def test_force_refresh_button_calls_coordinator(hass) -> None:
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
    coordinator.async_request_device_location_refresh = AsyncMock()

    description = next(item for item in BUTTONS if item.key == "refresh_location")
    entity = ZTEKidsButton(coordinator, "imei-1", description)

    await entity.async_press()

    coordinator.async_request_device_location_refresh.assert_awaited_once_with("imei-1")


@pytest.mark.asyncio
async def test_coordinator_requests_location_refresh_and_snapshot_refresh(hass) -> None:
    client = MagicMock()
    client.devices.request_location_refresh = AsyncMock(return_value={"code": 0})

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
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
    coordinator._session = data.session
    coordinator.async_request_refresh = AsyncMock()

    await coordinator.async_request_device_location_refresh("imei-1")

    client.devices.request_location_refresh.assert_awaited_once_with(data.session, "imei-1")
    coordinator.async_request_refresh.assert_awaited_once()

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import (
    CONF_DEVICE_POLLING,
    CONF_POLLING_ENABLED,
    CONF_POLLING_INTERVAL,
    DOMAIN,
)
from custom_components.zte_kids.coordinator import CoordinatorData, ZTEKidsDataUpdateCoordinator
from custom_components.zte_kids.sdk.config import Environment
from custom_components.zte_kids.sdk.models import AccountProfile, Credentials, Device, Session

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TEST_USERNAME = "user@example.com"
TEST_PASSWORD = "secret"


def _entry_data() -> dict[str, str | int]:
    return {
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD,
    }


async def test_config_flow_user_form_only_includes_credentials(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert {key.schema for key in result["data_schema"].schema} == {"username", "password"}


async def test_config_flow_creates_entry(hass) -> None:
    shared_http_client = object()

    with patch(
        "custom_components.zte_kids.config_flow.get_async_client",
        return_value=shared_http_client,
    ) as get_client, patch("custom_components.zte_kids.config_flow.ZTEKidsClient") as client_cls:
        client = client_cls.return_value
        client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
        client.aclose = AsyncMock()

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_entry_data(),
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_USERNAME
    assert result["data"] == _entry_data()
    get_client.assert_called_once_with(hass)
    client_cls.assert_called_once_with(
        environment=Environment.PRODUCTION,
        http_client=shared_http_client,
        close_http_client=False,
    )
    client.auth.login.assert_awaited_once()
    client.aclose.assert_awaited_once()


async def test_config_flow_aborts_if_account_already_configured(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
    )
    entry.add_to_hass(hass)

    with patch("custom_components.zte_kids.config_flow.ZTEKidsClient") as client_cls:
        client = client_cls.return_value
        client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
        client.aclose = AsyncMock()

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_entry_data(),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client.aclose.assert_awaited_once()


async def test_reconfigure_updates_existing_entry(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
    )
    entry.add_to_hass(hass)

    with patch("custom_components.zte_kids.config_flow.ZTEKidsClient") as client_cls:
        client = client_cls.return_value
        client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
        client.aclose = AsyncMock()

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                **_entry_data(),
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == _entry_data()
    client.auth.login.assert_awaited_once()
    client.aclose.assert_awaited_once()


async def test_reauth_updates_existing_entry_password(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
    )
    entry.add_to_hass(hass)

    with patch("custom_components.zte_kids.config_flow.ZTEKidsClient") as client_cls:
        client = client_cls.return_value
        client.auth.login = AsyncMock(
            return_value=Session(access_token="token", openid="openid")
        )
        client.aclose = AsyncMock()

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"password": "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"
    assert entry.data["username"] == TEST_USERNAME
    client.auth.login.assert_awaited_once()
    client.aclose.assert_awaited_once()


async def test_async_setup_entry_sets_runtime_data_and_unloads(hass) -> None:
    fake_client = MagicMock()
    fake_client.aclose = AsyncMock()
    shared_http_client = object()

    fake_coordinator = MagicMock()
    fake_coordinator.async_config_entry_first_refresh = AsyncMock()
    fake_coordinator.async_shutdown = AsyncMock()
    fake_coordinator.data = CoordinatorData(
        session=Session(access_token="token", openid="openid"),
        profile=AccountProfile(openid="openid"),
        devices={},
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.zte_kids.get_async_client",
        return_value=shared_http_client,
    ) as get_client, patch(
        "custom_components.zte_kids.ZTEKidsClient",
        return_value=fake_client,
    ) as client_cls, patch(
        "custom_components.zte_kids.ZTEKidsDataUpdateCoordinator",
        return_value=fake_coordinator,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    get_client.assert_called_once_with(hass)
    client_cls.assert_called_once_with(
        environment=Environment.PRODUCTION,
        http_client=shared_http_client,
        close_http_client=False,
    )
    assert entry.runtime_data.client is fake_client
    assert entry.runtime_data.coordinator is fake_coordinator
    fake_coordinator.async_config_entry_first_refresh.assert_awaited_once()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake_coordinator.async_shutdown.assert_awaited_once()
    fake_client.aclose.assert_awaited_once()


async def test_coordinator_respects_disabled_device_polling(hass) -> None:
    fake_client = MagicMock()
    fake_client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
    fake_client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    fake_client.devices.list_related_devices = AsyncMock(
        side_effect=[
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 50}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 10}}
                )
            ],
        ]
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
    )
    entry.add_to_hass(hass)

    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=fake_client,
        credentials=Credentials(username=TEST_USERNAME, password=TEST_PASSWORD),
        config_entry=entry,
    )

    await coordinator.async_refresh()
    assert coordinator.data.devices["imei-1"].battery == 50
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

    assert fake_client.devices.list_related_devices.await_count == 2
    assert coordinator.data.devices["imei-1"].battery == 50
    assert coordinator.device_polling_enabled("imei-1") is False


async def test_coordinator_respects_device_polling_interval(hass) -> None:
    fake_client = MagicMock()
    fake_client.auth.login = AsyncMock(return_value=Session(access_token="token", openid="openid"))
    fake_client.auth.query_profile = AsyncMock(return_value=AccountProfile(openid="openid"))
    fake_client.devices.list_related_devices = AsyncMock(
        side_effect=[
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 11}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 22}}
                )
            ],
            [
                Device.from_payload(
                    {"imei": "imei-1", "name": "Watch 1", "battery": {"percent": 33}}
                )
            ],
        ]
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
        options={
            CONF_DEVICE_POLLING: {
                "imei-1": {
                    CONF_POLLING_INTERVAL: 1800,
                }
            }
        },
    )
    entry.add_to_hass(hass)

    clock = {"now": 0.0}
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=fake_client,
        credentials=Credentials(username=TEST_USERNAME, password=TEST_PASSWORD),
        config_entry=entry,
    )

    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_refresh()
        assert coordinator.data.devices["imei-1"].battery == 11
        clock["now"] = 60.0
        await coordinator.async_refresh()
        assert coordinator.data.devices["imei-1"].battery == 11
        clock["now"] = 1801.0
        await coordinator.async_refresh()

    assert fake_client.devices.list_related_devices.await_count == 3
    assert coordinator.data.devices["imei-1"].battery == 33
    assert coordinator.device_polling_interval("imei-1") == 1800


async def test_coordinator_update_interval_uses_device_polling_inputs(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data=_entry_data(),
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
        credentials=Credentials(username=TEST_USERNAME, password=TEST_PASSWORD),
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

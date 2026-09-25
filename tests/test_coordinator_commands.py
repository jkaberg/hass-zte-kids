"""Behaviour of the shared command path: retry, serialisation, error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import DOMAIN
from custom_components.zte_kids.coordinator import (
    CoordinatorData,
    ZTEKidsDataUpdateCoordinator,
)
from custom_components.zte_kids.sdk import commands
from custom_components.zte_kids.sdk.exceptions import APIError, SessionExpiredError
from custom_components.zte_kids.sdk.models import (
    AccountProfile,
    ChatSession,
    Credentials,
    Device,
    DeviceSnapshot,
    Session,
)


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, client) -> ZTEKidsDataUpdateCoordinator:
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_entry(hass),
    )
    data = CoordinatorData(
        session=Session(access_token="token", openid="openid"),
        profile=AccountProfile(openid="openid"),
        devices={
            "imei-1": DeviceSnapshot(
                device=Device(device_id="imei-1", name="Watch 1"),
                raw={"imei": "imei-1", "name": "Watch 1", "support_find": 1},
            )
        },
    )
    coordinator.async_set_updated_data(data)
    coordinator._latest_data = data
    coordinator._session = data.session
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_send_command_dispatches_with_the_active_session(hass) -> None:
    client = MagicMock()
    client.configuration.send_command = AsyncMock()
    coordinator = _coordinator(hass, client)

    await coordinator.async_send_command("imei-1", commands.RESTART)

    client.configuration.send_command.assert_awaited_once()
    session, device_id, command = client.configuration.send_command.await_args.args
    assert session.access_token == "token"
    assert device_id == "imei-1"
    assert command is commands.RESTART


@pytest.mark.asyncio
async def test_unknown_device_raises_a_translated_error(hass) -> None:
    coordinator = _coordinator(hass, MagicMock())

    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_send_command("imei-nope", commands.FIND_WATCH)

    assert err.value.translation_key == "unknown_device"


@pytest.mark.asyncio
async def test_expired_session_is_retried_once_after_relogin(hass) -> None:
    refreshed = Session(access_token="token-2", openid="openid")
    client = MagicMock()
    client.auth.login = AsyncMock(return_value=refreshed)
    client.configuration.send_command = AsyncMock(
        side_effect=[SessionExpiredError(code=1002, message="expired"), None]
    )
    coordinator = _coordinator(hass, client)

    await coordinator.async_send_command("imei-1", commands.FIND_WATCH)

    assert client.auth.login.await_count == 1
    assert client.configuration.send_command.await_count == 2
    assert client.configuration.send_command.await_args.args[0] is refreshed


@pytest.mark.asyncio
async def test_relogin_failure_surfaces_as_reauth(hass) -> None:
    client = MagicMock()
    client.auth.login = AsyncMock(side_effect=APIError(code=1, message="nope"))
    client.configuration.send_command = AsyncMock(
        side_effect=SessionExpiredError(code=1002, message="expired")
    )
    coordinator = _coordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_send_command("imei-1", commands.FIND_WATCH)


@pytest.mark.asyncio
async def test_api_errors_become_translated_command_failures(hass) -> None:
    client = MagicMock()
    client.configuration.send_command = AsyncMock(
        side_effect=APIError(code=4001, message="not permitted")
    )
    coordinator = _coordinator(hass, client)

    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_send_command("imei-1", commands.POWER_OFF)

    assert err.value.translation_key == "command_failed"
    assert err.value.translation_placeholders["device"] == "Watch 1"


@pytest.mark.asyncio
async def test_rapid_repeats_are_rejected_not_queued(hass) -> None:
    client = MagicMock()
    client.configuration.send_command = AsyncMock()
    coordinator = _coordinator(hass, client)

    clock = {"now": 100.0}
    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_send_command("imei-1", commands.FIND_WATCH)

        clock["now"] = 101.0
        with pytest.raises(HomeAssistantError) as err:
            await coordinator.async_send_command("imei-1", commands.FIND_WATCH)
        assert err.value.translation_key == "command_too_soon"

        clock["now"] = 120.0
        await coordinator.async_send_command("imei-1", commands.FIND_WATCH)

    assert client.configuration.send_command.await_count == 2


@pytest.mark.asyncio
async def test_message_send_resolves_and_caches_the_chat_session(hass) -> None:
    client = MagicMock()
    client.chat.list_sessions = AsyncMock(
        return_value=[
            ChatSession(chat_id="other", device_id="imei-9"),
            ChatSession(chat_id="chat-1", device_id="imei-1", chat_type=2),
        ]
    )
    client.chat.send_text = AsyncMock(return_value={"code": 0})
    coordinator = _coordinator(hass, client)

    clock = {"now": 0.0}
    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_send_message("imei-1", "first")
        clock["now"] = 60.0
        await coordinator.async_send_message("imei-1", "second")

    assert client.chat.list_sessions.await_count == 1
    assert client.chat.send_text.await_count == 2
    assert client.chat.send_text.await_args.args[1].chat_id == "chat-1"


@pytest.mark.asyncio
async def test_message_send_falls_back_to_the_legacy_gateway(hass) -> None:
    client = MagicMock()
    client.chat.list_sessions = AsyncMock(return_value=[])
    client.chat.send_text = AsyncMock()
    client.chat.send_text_legacy = AsyncMock(return_value={"code": 0})
    coordinator = _coordinator(hass, client)

    clock = {"now": 0.0}
    with patch(
        "custom_components.zte_kids.coordinator.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_send_message("imei-1", "first")
        clock["now"] = 60.0
        await coordinator.async_send_message("imei-1", "second")

    client.chat.send_text.assert_not_awaited()
    assert client.chat.send_text_legacy.await_count == 2
    # The failed modern attempt is made once, then remembered.
    assert client.chat.list_sessions.await_count == 1


@pytest.mark.asyncio
async def test_capabilities_come_from_the_device_payload(hass) -> None:
    coordinator = _coordinator(hass, MagicMock())

    capabilities = coordinator.device_capabilities("imei-1")

    assert capabilities.supports("find")
    # An absent flag falls back to supported rather than hiding the entity.
    assert capabilities.supports("chat")
    assert not capabilities.supports("chat", default=False)


@pytest.mark.asyncio
async def test_auth_failure_does_not_trigger_the_legacy_fallback(hass) -> None:
    """A rejected session is not evidence that the device needs the old path."""
    client = MagicMock()
    client.auth.login = AsyncMock(side_effect=APIError(code=1, message="nope"))
    client.chat.list_sessions = AsyncMock(
        side_effect=SessionExpiredError(code=1002, message="expired")
    )
    client.chat.send_text_legacy = AsyncMock()
    coordinator = _coordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_send_message("imei-1", "hello")

    client.chat.send_text_legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_offline_watch_is_not_reported_as_an_integration_failure(hass) -> None:
    """Codes 1153 and 5001 mean the watch is unreachable, which the user can act on."""
    from homeassistant.exceptions import ServiceValidationError

    for code in (1153, 5001):
        client = MagicMock()
        client.configuration.send_command = AsyncMock(
            side_effect=APIError(code=code, message="设备离线")
        )
        coordinator = _coordinator(hass, client)

        with pytest.raises(ServiceValidationError) as err:
            await coordinator.async_send_command("imei-1", commands.RESTART)

        assert err.value.translation_key == "device_offline"
        # The service's own Chinese text must not reach the user.
        assert "设备" not in str(err.value.translation_placeholders)


@pytest.mark.asyncio
async def test_other_api_errors_remain_integration_failures(hass) -> None:
    client = MagicMock()
    client.configuration.send_command = AsyncMock(
        side_effect=APIError(code=4001, message="not permitted")
    )
    coordinator = _coordinator(hass, client)

    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_send_command("imei-1", commands.RESTART)

    assert err.value.translation_key == "command_failed"

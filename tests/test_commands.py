"""Wire-format tests for the device command endpoint.

These assert the exact body handed to the transport. For a reverse-engineered
protocol that is the regression net that matters: a refactor that drops a field
or renames a key produces a request the server accepts and the watch ignores,
which no higher-level test would catch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.zte_kids.sdk import commands
from custom_components.zte_kids.sdk.client import ChatAPI, ConfigurationAPI
from custom_components.zte_kids.sdk.commands import CommandType, LocationMode
from custom_components.zte_kids.sdk.http import APIEnvelope
from custom_components.zte_kids.sdk.models import ChatSession, Session


def _transport() -> MagicMock:
    transport = MagicMock()
    transport.request = AsyncMock(
        return_value=APIEnvelope(code=0, message=None, data={}, raw={"code": 0})
    )
    return transport


def _session() -> Session:
    return Session(access_token="token-abc", openid="openid-1")


def test_one_shot_commands_carry_only_the_selector() -> None:
    assert commands.FIND_WATCH.body("imei-1") == {"deviceId": "imei-1", "type": 4}
    assert commands.POWER_OFF.body("imei-1") == {"deviceId": "imei-1", "type": 7}
    assert commands.RESTART.body("imei-1") == {"deviceId": "imei-1", "type": 13}


def test_restart_is_type_13_not_factory_reset() -> None:
    """Type 13 is the Remote Control screen's Restart button.

    Confirmed against the confirmation dialog it is wired to: "Are you sure you
    want to restart the ... watch?". Factory reset is a separate unbind flow on
    a different endpoint entirely.
    """
    assert CommandType.RESTART == 13
    assert CommandType.POWER_OFF == 7


def test_switch_commands_use_the_status_domain() -> None:
    assert commands.switch(CommandType.LONG_LIFE_MODE, True).body("imei-1") == {
        "deviceId": "imei-1",
        "type": 2,
        "status": 1,
    }
    assert commands.switch(CommandType.LONG_LIFE_MODE, False).body("imei-1") == {
        "deviceId": "imei-1",
        "type": 2,
        "status": 2,
    }


def test_location_mode_uses_mode_not_status() -> None:
    assert commands.mode(CommandType.LOCATION_MODE, LocationMode.POWER_SAVING).body("imei-1") == {
        "deviceId": "imei-1",
        "type": 1,
        "mode": 3,
    }


def test_scheduled_power_off_nests_the_window() -> None:
    command = commands.scheduled_power_off(
        enabled=True, start_time="22:00", end_time="06:30"
    )
    assert command.body("imei-1") == {
        "deviceId": "imei-1",
        "type": 19,
        "status": 1,
        "rule": {"interval": {"startTime": "22:00", "endTime": "06:30"}},
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, True), (2, False), (0, None), (99, None), (None, None), ("1", True), ("x", None)],
)
def test_switch_to_bool_reports_unknown_values_as_unknown(value, expected) -> None:
    assert commands.switch_to_bool(value) is expected


@pytest.mark.asyncio
async def test_send_command_posts_to_the_config_endpoint() -> None:
    transport = _transport()
    api = ConfigurationAPI(transport)

    await api.send_command(_session(), "imei-1", commands.RESTART)

    transport.request.assert_awaited_once()
    args, kwargs = transport.request.await_args
    assert args == ("POST", "api/device/save/systemconfig")
    assert kwargs["token"] == "token-abc"
    assert kwargs["json_body"] == {"deviceId": "imei-1", "type": 13}


@pytest.mark.asyncio
async def test_tinychat_send_uses_the_recovered_constants() -> None:
    transport = _transport()
    api = ChatAPI(transport)
    chat_session = ChatSession(
        chat_id="chat-1",
        chat_type=2,
        device_id="imei-1",
        group_id="group-1",
        recv_id="recv-1",
    )

    await api.send_text(_session(), chat_session, "dinner at six")

    args, kwargs = transport.request.await_args
    assert args == ("POST", "api/chat/sendmsg")
    assert kwargs["json_body"] == {
        "token": "token-abc",
        "chatID": "chat-1",
        "chatType": 2,
        "recvID": "recv-1",
        "groupID": "group-1",
        "userType": 1,
        "contentType": 101,
        "content": "dinner at six",
    }


@pytest.mark.asyncio
async def test_legacy_send_targets_the_gateway_path() -> None:
    transport = _transport()
    api = ChatAPI(transport)

    await api.send_text_legacy(_session(), "imei-1", "dinner at six")

    args, kwargs = transport.request.await_args
    assert args == ("POST", "getway/single/imei-1/message")
    assert kwargs["json_body"] == {
        "openid": "openid-1",
        "accesstoken": "token-abc",
        "content": "dinner at six",
        "type": 1,
    }


@pytest.mark.asyncio
async def test_list_sessions_parses_a_bare_list() -> None:
    transport = _transport()
    transport.request = AsyncMock(
        return_value=APIEnvelope(
            code=0,
            message=None,
            data=[{"chatID": "c1", "deviceID": "imei-1", "chatType": 2}],
            raw={},
        )
    )
    api = ChatAPI(transport)

    sessions = await api.list_sessions(_session())

    assert len(sessions) == 1
    assert sessions[0].chat_id == "c1"
    assert sessions[0].matches("imei-1")


def test_chat_session_matches_on_recv_id_fallback() -> None:
    session = ChatSession(chat_id="c1", recv_id="imei-9")
    assert session.matches("imei-9")
    assert not session.matches("imei-1")


def test_location_mode_values_match_the_app_labels() -> None:
    """1/2/3 are Precision/Normal/Power saving, per BatterySavingActivity.I4()."""
    assert LocationMode.PRECISION == 1
    assert LocationMode.NORMAL == 2
    assert LocationMode.POWER_SAVING == 3


def test_switch_polarity_is_one_on_two_off() -> None:
    """Proven from SmsReceiveSettingsActivity.G4(): 1 renders checkbox_selected."""
    assert commands.SWITCH_ON == 1
    assert commands.SWITCH_OFF == 2
    assert commands.bool_to_switch(True) == 1
    assert commands.bool_to_switch(False) == 2


def test_shutdown_protection_sends_status_and_password_together() -> None:
    command = commands.shutdown_protection(enabled=True, password="1234")
    assert command.body("imei-1") == {
        "deviceId": "imei-1",
        "type": 25,
        "shutdownVo": {"status": 1, "shutdownPwd": "1234"},
    }


def test_shutdown_protection_omits_an_unknown_password() -> None:
    command = commands.shutdown_protection(enabled=False, password=None)
    assert command.body("imei-1")["shutdownVo"] == {"status": 2}


def test_sos_numbers_always_sends_the_whole_set() -> None:
    command = commands.sos_numbers(("111", None, "333"))
    assert command.body("imei-1") == {
        "deviceId": "imei-1",
        "type": 12,
        "sos": {"sos1": "111", "sos2": "", "sos3": "333"},
    }

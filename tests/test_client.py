from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import httpx
import pytest

from custom_components.zte_kids.sdk.client import DeviceAPI
from custom_components.zte_kids.sdk.config import ENVIRONMENTS, Environment, PlatformMetadata
from custom_components.zte_kids.sdk.http import SignedAsyncTransport
from custom_components.zte_kids.sdk.models import Session


@pytest.mark.asyncio
async def test_request_location_refresh_posts_gateway_form_fields() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": None})

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant", model="Linux", os_name="Android", release="test"
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = DeviceAPI(transport)

    response = await api.request_location_refresh(
        Session(access_token="token-1", openid="openid-1"),
        "imei-1",
    )

    assert response["code"] == 0
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert captured_request.url.path.endswith("/getway/devices/imei-1/location/last")
    form_data = parse_qs(captured_request.content.decode("utf-8"))
    assert form_data == {
        "openid": ["openid-1"],
        "accesstoken": ["token-1"],
    }

    await transport.aclose()


@pytest.mark.asyncio
async def test_list_related_devices_parses_owned_and_chat_group_lists() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "OwnedDevices": [
                        {
                            "imei": "imei-admin",
                            "groupid": "group-admin",
                            "name": "Admin Watch",
                        }
                    ],
                    "ChatGroupDevices": [
                        {
                            "imei": "imei-member",
                            "groupid": "group-member",
                            "single_groupid": "single-member",
                            "name": "Member Watch",
                            "identity": "member",
                        }
                    ],
                },
            },
        )

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant", model="Linux", os_name="Android", release="test"
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = DeviceAPI(transport)

    devices = await api.list_related_devices(
        Session(access_token="token-1", openid="openid-1"),
    )

    assert [device.device_id for device in devices] == ["imei-admin", "imei-member"]
    assert devices[0].is_admin is True
    assert devices[1].is_admin is False
    assert devices[1].single_group_id == "single-member"

    await transport.aclose()


@pytest.mark.asyncio
async def test_list_related_devices_parses_top_level_gateway_payload() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "chatGroupDevices": [
                    {
                        "imei": "imei-1",
                        "groupid": "group-1",
                        "identity": "admin",
                        "single_groupid": "single-1",
                        "name": "Watch 1",
                    }
                ],
                "ad_swtich": "true",
            },
        )

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant", model="Linux", os_name="Android", release="test"
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = DeviceAPI(transport)

    devices = await api.list_related_devices(
        Session(access_token="token-1", openid="openid-1"),
    )

    assert len(devices) == 1
    assert devices[0].device_id == "imei-1"
    assert devices[0].group_id == "group-1"
    assert devices[0].single_group_id == "single-1"
    assert devices[0].is_admin is True

    await transport.aclose()


@pytest.mark.asyncio
async def test_get_system_config_includes_token_in_json_body() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {}})

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant", model="Linux", os_name="Android", release="test"
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = DeviceAPI(transport)

    await api._transport.request(
        "POST",
        "api/device/query/systemconfig",
        token="token-1",
        json_body={"deviceId": "imei-1", "type": 1},
        extra_headers={"Content-Type": "application/json"},
    )

    assert captured_request is not None
    assert captured_request.method == "POST"
    assert captured_request.url.path.endswith("/api/device/query/systemconfig")
    assert json.loads(captured_request.content.decode("utf-8")) == {
        "deviceId": "imei-1",
        "type": 1,
        "token": "token-1",
    }

    await transport.aclose()


@pytest.mark.asyncio
async def test_set_system_config_includes_token_in_json_body() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": None})

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant", model="Linux", os_name="Android", release="test"
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await transport.request(
        "POST",
        "api/device/save/systemconfig",
        token="token-1",
        json_body={"deviceId": "imei-1", "type": 14, "status": 1},
        extra_headers={"Content-Type": "application/json"},
    )

    assert captured_request is not None
    assert captured_request.url.path.endswith("/api/device/save/systemconfig")
    assert json.loads(captured_request.content.decode("utf-8")) == {
        "deviceId": "imei-1",
        "type": 14,
        "status": 1,
        "token": "token-1",
    }

    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_does_not_close_injected_client_when_not_owned() -> None:
    external_client = MagicMock(spec=httpx.AsyncClient)
    external_client.aclose = AsyncMock()

    transport = SignedAsyncTransport(
        config=ENVIRONMENTS[Environment.PRODUCTION],
        platform=PlatformMetadata(
            brand="HomeAssistant",
            model="Linux",
            os_name="Android",
            release="test",
        ),
        client=external_client,
        close_client=False,
    )

    await transport.aclose()

    external_client.aclose.assert_not_awaited()

def test_debug_logs_do_not_leak_a_child_s_data() -> None:
    """A debug log usually ends up pasted into a public issue.

    Secrets and personal data are replaced outright; identifiers keep a short
    tail so lines can still be correlated with each other.
    """
    from custom_components.zte_kids.sdk.http import _redact_payload

    redacted = _redact_payload(
        {
            "token": "secret-token",
            "email": "parent@example.com",
            "sos": {"sos1": "+4790000001", "sos2": "", "sos3": None},
            "shutdownVo": {"status": 1, "shutdownPwd": "1234"},
            "lastLocation": {"lat": 59.9148, "lon": 10.7522, "address": "Home", "radius": 30},
            "imei": "869123456789012",
            "openid": "0123456789abcdef01234567",
            "battery": {"percent": 91},
        }
    )

    assert redacted["token"] == "***"
    assert redacted["email"] == "***"
    assert redacted["sos"] == {"sos1": "***", "sos2": "***", "sos3": "***"}
    assert redacted["shutdownVo"]["shutdownPwd"] == "***"
    assert redacted["lastLocation"]["lat"] == "***"
    assert redacted["lastLocation"]["lon"] == "***"
    assert redacted["lastLocation"]["address"] == "***"

    # Identifiers stay correlatable but not publishable.
    assert redacted["imei"] == "***9012"
    assert redacted["openid"] == "***4567"

    # Values that are neither secret nor personal are left alone.
    assert redacted["shutdownVo"]["status"] == 1
    assert redacted["lastLocation"]["radius"] == 30
    assert redacted["battery"]["percent"] == 91

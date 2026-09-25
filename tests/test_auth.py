from __future__ import annotations

from base64 import b64decode
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx
import pytest

from custom_components.zte_kids.sdk.auth import PasswordCodec, build_signature
from custom_components.zte_kids.sdk.client import AuthAPI
from custom_components.zte_kids.sdk.config import ENVIRONMENTS, Environment
from custom_components.zte_kids.sdk.exceptions import CaptchaRequiredError
from custom_components.zte_kids.sdk.http import SignedAsyncTransport
from custom_components.zte_kids.sdk.models import CaptchaAnswer, Credentials


def test_signature_preserves_sorted_top_level_fields() -> None:
    config = ENVIRONMENTS[Environment.PRODUCTION]
    result = build_signature(
        config=config,
        method="POST",
        json_body={"password": "cipher", "loginName": "user@example.com"},
        timestamp="1710000000000",
        nonce="abcdef0123456789abcdef0123456789",
    )

    assert result.app_key == config.app_key
    assert result.timestamp == "1710000000000"
    assert result.nonce == "abcdef0123456789abcdef0123456789"
    assert len(result.sign) == 64


def test_password_codec_matches_aes_gcm_layout() -> None:
    config = ENVIRONMENTS[Environment.PRODUCTION]
    codec = PasswordCodec(config)
    nonce = bytes.fromhex("00112233445566778899aabb")
    encoded = codec.encrypt("password123", nonce=nonce)

    decoded = b64decode(encoded)
    assert decoded[:12] == nonce

    plaintext = AESGCM(config.password_key).decrypt(decoded[:12], decoded[12:], None)
    assert plaintext.decode("utf-8") == "password123"


@pytest.mark.asyncio
async def test_login_includes_optional_captcha_fields() -> None:
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={"code": 0, "msg": "ok", "data": {"accesstoken": "token", "openid": "user"}},
        )

    config = ENVIRONMENTS[Environment.PRODUCTION]
    transport = SignedAsyncTransport(
        config=config,
        platform=configure_platform(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = AuthAPI(transport, PasswordCodec(config), configure_platform())

    session = await api.login(
        Credentials(username="user@example.com", password="password123"),
        captcha_answer=CaptchaAnswer(kid="kid-1", jigsaw_code="123,45"),
    )

    assert session.access_token == "token"
    assert captured_request is not None
    payload = json.loads(captured_request.content.decode("utf-8"))
    assert payload["kid"] == "kid-1"
    assert payload["jigsawCode"] == "123,45"

    await transport.aclose()


@pytest.mark.asyncio
async def test_fetch_captcha_challenge_parses_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "kid": "kid-123",
                    "bigImg": "data:image/png;base64,AAAA",
                    "smallImg": "data:image/png;base64,BBBB",
                    "yHeight": 27,
                },
            },
        )

    config = ENVIRONMENTS[Environment.PRODUCTION]
    transport = SignedAsyncTransport(
        config=config,
        platform=configure_platform(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = AuthAPI(transport, PasswordCodec(config), configure_platform())

    challenge = await api.fetch_captcha_challenge()

    assert challenge.kid == "kid-123"
    assert challenge.big_img == "data:image/png;base64,AAAA"
    assert challenge.small_img == "data:image/png;base64,BBBB"
    assert challenge.y_height == 27

    await transport.aclose()


@pytest.mark.asyncio
async def test_login_surfaces_captcha_required_without_solver() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 2160, "msg": "Wrong answer, please answer again"})

    config = ENVIRONMENTS[Environment.PRODUCTION]
    transport = SignedAsyncTransport(
        config=config,
        platform=configure_platform(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    api = AuthAPI(transport, PasswordCodec(config), configure_platform())

    with pytest.raises(CaptchaRequiredError):
        await api.login(Credentials(username="user@example.com", password="password123"))

    await transport.aclose()


def configure_platform():
    from custom_components.zte_kids.sdk.config import PlatformMetadata

    return PlatformMetadata(brand="HomeAssistant", model="Linux", os_name="Android", release="test")

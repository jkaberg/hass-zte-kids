from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .auth import PasswordCodec
from .commands import Command
from .config import ENVIRONMENTS, Environment, PlatformMetadata
from .exceptions import (
    APIError,
    CaptchaAnswerIncorrectError,
    CaptchaRefreshRequiredError,
    CaptchaRequiredError,
    VerificationChallengeError,
)
from .http import SignedAsyncTransport
from .models import (
    CONTENT_TYPE_TEXT,
    USER_TYPE_ACCOUNT,
    AccountProfile,
    CaptchaAnswer,
    CaptchaChallenge,
    ChatSession,
    Credentials,
    Device,
    DeviceSnapshot,
    Session,
)


@dataclass(frozen=True, slots=True)
class BindRequest:
    imei: str
    relationship: str
    device_default_name: str
    image_type: int = 1
    image_url: str | None = None
    phone: str | None = None


CaptchaSolver = Callable[[CaptchaChallenge], Awaitable[CaptchaAnswer | None]]


class AuthAPI:
    def __init__(
        self, transport: SignedAsyncTransport, codec: PasswordCodec, platform: PlatformMetadata
    ) -> None:
        self._transport = transport
        self._codec = codec
        self._platform = platform

    async def fetch_captcha_challenge(self) -> CaptchaChallenge:
        envelope = await self._transport.request(
            "POST",
            "api/account/captchaImage",
            need_token=False,
            json_body={},
            extra_headers={"Content-Type": "application/json"},
        )
        return CaptchaChallenge.from_payload(_ensure_dict(envelope.data))

    async def login(
        self,
        credentials: Credentials,
        *,
        captcha_answer: CaptchaAnswer | None = None,
        captcha_solver: CaptchaSolver | None = None,
    ) -> Session:
        if captcha_answer is not None:
            envelope = await self._login_request(credentials, captcha_answer=captcha_answer)
            return Session.from_payload(_ensure_dict(envelope.data))

        try:
            envelope = await self._login_request(credentials)
            return Session.from_payload(_ensure_dict(envelope.data))
        except Exception as err:
            challenge_trigger = _coerce_login_challenge_error(err)
            if challenge_trigger is None:
                raise

        if captcha_solver is None:
            raise CaptchaRequiredError(
                message=challenge_trigger.message,
                payload=challenge_trigger.payload,
            ) from challenge_trigger

        challenge = await self.fetch_captcha_challenge()
        latest_error: VerificationChallengeError | APIError = challenge_trigger
        for _ in range(2):
            solved = await captcha_solver(challenge)
            if solved is None:
                raise CaptchaRequiredError(
                    message=latest_error.message,
                    challenge=challenge,
                    payload=latest_error.payload,
                ) from latest_error
            try:
                envelope = await self._login_request(credentials, captcha_answer=solved)
                return Session.from_payload(_ensure_dict(envelope.data))
            except CaptchaRefreshRequiredError as refresh_error:
                latest_error = refresh_error
                challenge = await self.fetch_captcha_challenge()
            except CaptchaAnswerIncorrectError as incorrect_error:
                raise CaptchaRequiredError(
                    message=incorrect_error.message,
                    challenge=challenge,
                    payload=incorrect_error.payload,
                ) from incorrect_error

        raise CaptchaRequiredError(
            message=latest_error.message,
            challenge=challenge,
            payload=latest_error.payload,
        ) from latest_error

    async def _login_request(
        self,
        credentials: Credentials,
        *,
        captcha_answer: CaptchaAnswer | None = None,
    ):
        payload = {
            "loginName": credentials.username,
            "password": self._codec.encrypt(credentials.password),
            "dypwdFlag": "N",
            "mobileType": self._platform.mobile_type,
        }
        if captcha_answer is not None:
            payload["kid"] = captcha_answer.kid
            payload["jigsawCode"] = captcha_answer.jigsaw_code

        envelope = await self._transport.request(
            "POST",
            "api/account/login",
            need_token=False,
            json_body=payload,
            extra_headers={"Content-Type": "application/json"},
        )
        return envelope

    async def query_profile(self, session: Session) -> AccountProfile:
        envelope = await self._transport.request(
            "POST",
            "api/account/query",
            token=session.access_token,
            need_token=False,
            json_body={"token": session.access_token},
            extra_headers={"Content-Type": "application/json"},
        )
        return AccountProfile.from_payload(_ensure_dict(envelope.data))

    async def logout(self, session: Session) -> None:
        await self._transport.request(
            "POST",
            "api/account/logout",
            token=session.access_token,
            need_token=False,
            json_body={"token": session.access_token},
            extra_headers={"Content-Type": "application/json"},
        )


class DeviceAPI:
    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def list_related_devices(self, session: Session) -> list[Device]:
        envelope = await self._transport.request(
            "GET",
            f"getway/accounts/{session.openid}/related-device",
            token=session.access_token,
            query_params={"accesstoken": session.access_token},
        )
        return _parse_related_devices(envelope.data)

    async def request_location_refresh(self, session: Session, imei: str) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            f"getway/devices/{imei}/location/last",
            token=session.access_token,
            need_token=False,
            form_fields={
                "openid": session.openid,
                "accesstoken": session.access_token,
            },
        )
        return _ensure_dict(envelope.raw)

    async def query_firmware(self, session: Session, device_id: str) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            "api/device/upgrade",
            token=session.access_token,
            json_body={"deviceId": device_id},
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.data)

    async def apply_bind(self, session: Session, request: BindRequest) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            "api/account/applybind",
            token=session.access_token,
            need_token=False,
            json_body={
                "imei": request.imei,
                "token": session.access_token,
                "relationship": request.relationship,
                "imgType": request.image_type,
                "deviceDefaultName": request.device_default_name,
                "imgUrl": request.image_url,
                "phone": request.phone,
            },
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.raw)


class ConfigurationAPI:
    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def get_system_config(
        self,
        session: Session,
        device_id: str,
        *,
        config_type: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"deviceId": device_id}
        if config_type is not None:
            body["type"] = config_type
        envelope = await self._transport.request(
            "POST",
            "api/device/query/systemconfig",
            token=session.access_token,
            json_body=body,
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.data)

    async def set_system_config(
        self,
        session: Session,
        *,
        device_id: str,
        command_type: int,
        payload: dict[str, Any],
    ) -> None:
        body = {"deviceId": device_id, "type": command_type, **payload}
        await self._transport.request(
            "POST",
            "api/device/save/systemconfig",
            token=session.access_token,
            json_body=body,
            extra_headers={"Content-Type": "application/json"},
        )

    async def send_command(
        self,
        session: Session,
        device_id: str,
        command: Command,
    ) -> None:
        """Dispatch a :class:`Command` to a device.

        The server acknowledging a command means it accepted the request, not
        that the watch executed it. Nothing here waits for the watch.
        """
        await self.set_system_config(
            session,
            device_id=device_id,
            command_type=int(command.command_type),
            payload=command.payload,
        )


class ChatAPI:
    """Text messaging to a watch.

    Two stacks exist server-side and the app uses both: newer device families
    go through TinyChat under ``api/chat/*``, older ones through the legacy
    gateway. Callers should try :meth:`send_text` first and fall back to
    :meth:`send_text_legacy` when the modern path rejects the send.
    """

    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def list_sessions(self, session: Session) -> list[ChatSession]:
        envelope = await self._transport.request(
            "POST",
            "api/chat/list",
            token=session.access_token,
            json_body={"token": session.access_token},
            extra_headers={"Content-Type": "application/json"},
        )
        return _parse_chat_sessions(envelope.data)

    async def send_text(
        self,
        session: Session,
        chat_session: ChatSession,
        message: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "token": session.access_token,
            "chatID": chat_session.chat_id,
            "chatType": chat_session.chat_type,
            "recvID": chat_session.recv_id,
            "groupID": chat_session.group_id,
            "userType": USER_TYPE_ACCOUNT,
            "contentType": CONTENT_TYPE_TEXT,
            "content": message,
        }
        envelope = await self._transport.request(
            "POST",
            "api/chat/sendmsg",
            token=session.access_token,
            json_body=body,
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.raw)

    async def send_text_legacy(
        self,
        session: Session,
        device_id: str,
        message: str,
    ) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            f"getway/single/{device_id}/message",
            token=session.access_token,
            json_body={
                "openid": session.openid,
                "accesstoken": session.access_token,
                "content": message,
                "type": 1,
            },
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.raw)


class LocationAPI:
    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def reverse_geocode(
        self,
        session: Session,
        *,
        device_id: str,
        lat: float,
        lon: float,
    ) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            "api/baiduGps/getRealTimeAddrByGps",
            token=session.access_token,
            need_token=False,
            json_body={
                "imei": device_id,
                "lat": lat,
                "lon": lon,
            },
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.data)


class SportAPI:
    """Daily activity totals and the step goal."""

    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def query_daily(
        self,
        session: Session,
        device_id: str,
        *,
        timezone_offset: int = 0,
        timezone_name: str = "UTC",
    ) -> list[dict[str, Any]]:
        envelope = await self._transport.request(
            "POST",
            "api/sport/query/daily",
            token=session.access_token,
            json_body={
                "deviceId": device_id,
                "timeZone": timezone_offset,
                "timezoneStr": timezone_name,
            },
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_list(envelope.data)

    async def set_aim(self, session: Session, device_id: str, aim: int) -> None:
        await self._transport.request(
            "POST",
            "api/sport/aim",
            token=session.access_token,
            json_body={"deviceId": device_id, "aim": int(aim)},
            extra_headers={"Content-Type": "application/json"},
        )

    async def query_aim(self, session: Session, device_id: str) -> dict[str, Any]:
        envelope = await self._transport.request(
            "POST",
            "api/sport/aim",
            token=session.access_token,
            json_body={"deviceId": device_id},
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_dict(envelope.data)


class GuardAPI:
    """Safe zones ("security guard" rules)."""

    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def list_rules(self, session: Session, device_id: str) -> list[dict[str, Any]]:
        envelope = await self._transport.request(
            "POST",
            "api/guardrule/query",
            token=session.access_token,
            json_body={"imei": device_id},
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_list(envelope.data)

    async def set_rule_status(
        self,
        session: Session,
        *,
        device_id: str,
        security_guard_id: str,
        enabled: bool,
    ) -> None:
        await self._transport.request(
            "POST",
            "api/guardrule/changeStatus",
            token=session.access_token,
            json_body={
                "imei": device_id,
                "securityGuardId": security_guard_id,
                "status": 1 if enabled else 2,
            },
            extra_headers={"Content-Type": "application/json"},
        )


class MessageAPI:
    def __init__(self, transport: SignedAsyncTransport) -> None:
        self._transport = transport

    async def unread_counts(self, session: Session) -> list[dict[str, Any]]:
        envelope = await self._transport.request(
            "POST",
            "api/message/devicelist",
            token=session.access_token,
            json_body={"openid": session.openid},
            extra_headers={"Content-Type": "application/json"},
        )
        return _ensure_list(envelope.data)


class ZTEKidsClient:
    def __init__(
        self,
        *,
        environment: Environment = Environment.PRODUCTION,
        platform: PlatformMetadata | None = None,
        transport: SignedAsyncTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
        close_http_client: bool = True,
    ) -> None:
        if transport is not None and http_client is not None:
            raise ValueError("Provide either transport or http_client, not both")

        self.platform = platform or PlatformMetadata.current()
        self.environment = ENVIRONMENTS[environment]
        self.transport = transport or SignedAsyncTransport(
            config=self.environment,
            platform=self.platform,
            client=http_client,
            close_client=close_http_client,
        )
        self.password_codec = PasswordCodec(self.environment)
        self.auth = AuthAPI(self.transport, self.password_codec, self.platform)
        self.devices = DeviceAPI(self.transport)
        self.configuration = ConfigurationAPI(self.transport)
        self.chat = ChatAPI(self.transport)
        self.sport = SportAPI(self.transport)
        self.guard = GuardAPI(self.transport)
        self.messages = MessageAPI(self.transport)
        self.location = LocationAPI(self.transport)

    async def aclose(self) -> None:
        await self.transport.aclose()

    async def bootstrap_account_state(
        self, credentials: Credentials
    ) -> tuple[Session, AccountProfile, list[DeviceSnapshot]]:
        session = await self.auth.login(credentials)
        profile = await self.auth.query_profile(session)
        devices = await self.devices.list_related_devices(session)
        snapshots = [
            DeviceSnapshot.from_payload(
                device.raw or {"imei": device.device_id, "name": device.name}
            )
            for device in devices
            if device.device_id
        ]
        return session, profile, snapshots


def _ensure_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("list", "rows", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _ensure_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {}


def _parse_chat_sessions(payload: Any) -> list[ChatSession]:
    if isinstance(payload, list):
        return [ChatSession.from_payload(item) for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("list", "rows", "sessions", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    ChatSession.from_payload(item) for item in value if isinstance(item, dict)
                ]

    return []


def _parse_related_devices(payload: Any) -> list[Device]:
    if isinstance(payload, list):
        return [Device.from_payload(item) for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    flattened: list[dict[str, Any]] = []
    keyed_lists = (
        ("OwnedDevices", True),
        ("ownedDevices", True),
        ("ChatGroupDevices", None),
        ("chatGroupDevices", None),
        ("list", None),
        ("rows", None),
        ("devices", None),
    )
    for key, admin_hint in keyed_lists:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            flattened.append(_with_admin_hint(item, admin_hint))

    if flattened:
        deduped: dict[str, Device] = {}
        ordered_devices: list[Device] = []
        for item in flattened:
            device = Device.from_payload(item)
            if not device.device_id or device.device_id in deduped:
                continue
            deduped[device.device_id] = device
            ordered_devices.append(device)
        return ordered_devices

    nested_payload = payload.get("data")
    if nested_payload is not payload:
        return _parse_related_devices(nested_payload)

    return []


def _with_admin_hint(payload: dict[str, Any], admin_hint: bool | None) -> dict[str, Any]:
    if admin_hint is None or "isAdmin" in payload:
        return payload

    updated = dict(payload)
    updated["isAdmin"] = admin_hint
    return updated


def _coerce_login_challenge_error(error: Exception) -> VerificationChallengeError | APIError | None:
    if isinstance(error, VerificationChallengeError):
        return error
    if not isinstance(error, APIError):
        return None

    message = error.message.lower()
    if any(token in message for token in ("captcha", "answer", "verification code", "jigsaw")):
        return error
    return None

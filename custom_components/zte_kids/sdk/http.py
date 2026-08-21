from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from .auth import SigningMaterial, build_signature
from .config import EnvironmentConfig, PlatformMetadata
from .exceptions import (
    APIError,
    CaptchaAnswerIncorrectError,
    CaptchaRefreshRequiredError,
    SessionExpiredError,
    VerificationCodeExpiredError,
)

LOGGER = logging.getLogger(__name__)
_REDACTED = "***"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=30.0)
# Replaced outright: knowing the value serves no debugging purpose and the
# value is either a secret or personal data about a child.
_SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "addrdetail",
    "address",
    "address_poi",
    "birthday",
    "coordinate",
    "email",
    "jigsawcode",
    "kid",
    "lat",
    "latitude",
    "loginname",
    "lon",
    "longitude",
    "password",
    "phone",
    "real_name",
    "shutdownpwd",
    "sos1",
    "sos2",
    "sos3",
    "token",
    "username",
}

# Partially masked instead: a debug log is useless if you cannot tell which
# watch or account a line belongs to, so enough is kept to correlate lines
# without publishing the identifier.
_PARTIAL_KEYS = {
    "bindno",
    "bindurl",
    "deviceid",
    "esimid",
    "groupid",
    "imei",
    "openid",
    "single_groupid",
    "singlegroupid",
}


@dataclass(frozen=True, slots=True)
class APIEnvelope:
    code: int | None
    message: str | None
    data: Any
    raw: Any


class SignedAsyncTransport:
    def __init__(
        self,
        *,
        config: EnvironmentConfig,
        platform: PlatformMetadata,
        client: httpx.AsyncClient | None = None,
        close_client: bool = True,
    ) -> None:
        self.config = config
        self.platform = platform
        self._close_client = close_client
        self._client = client or httpx.AsyncClient(
            base_url=config.api_base_url,
            timeout=_DEFAULT_TIMEOUT,
            headers={
                "Accept": "application/json",
                "Accept-Language": platform.accept_language,
                "User-Agent": platform.user_agent,
            },
        )

    async def aclose(self) -> None:
        if self._close_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        need_token: bool = True,
        query_params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
        form_fields: Mapping[str, object] | None = None,
        multipart_text_fields: Mapping[str, object] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> APIEnvelope:
        upper_method = method.upper()
        prepared_json = dict(json_body) if json_body is not None else None
        prepared_form = dict(form_fields) if form_fields is not None else None
        prepared_multipart = (
            dict(multipart_text_fields) if multipart_text_fields is not None else None
        )

        if upper_method == "POST" and token and need_token:
            if prepared_form is not None:
                prepared_form["token"] = token
            elif prepared_multipart is not None:
                prepared_multipart["token"] = token
            elif prepared_json is not None:
                prepared_json["token"] = token

        signing = build_signature(
            config=self.config,
            method=upper_method,
            query_params=query_params,
            json_body=prepared_json,
            form_fields=prepared_form,
            multipart_text_fields=prepared_multipart,
        )
        request_headers = {
            "Accept": "application/json",
            "token": token or "",
            "User-Agent": self.platform.user_agent,
            "Accept-Language": self.platform.accept_language,
        }
        if extra_headers is not None:
            request_headers.update(extra_headers)

        url = urljoin(self.config.api_base_url, path)
        merged_query = self._merge_query_params(query_params, signing)
        LOGGER.debug(
            "HTTP request %s %s headers=%s query=%s json=%s form=%s multipart=%s",
            upper_method,
            url,
            _redact_payload(request_headers),
            _redact_payload(merged_query),
            _redact_payload(prepared_json),
            _redact_payload(prepared_form),
            _redact_payload(prepared_multipart),
        )

        response = await self._client.request(
            upper_method,
            url,
            params=merged_query,
            json=prepared_json,
            data=prepared_form,
            files=self._multipart_to_httpx(prepared_multipart),
            headers=request_headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        LOGGER.debug(
            "HTTP response %s %s status=%s payload=%s",
            upper_method,
            url,
            response.status_code,
            _redact_payload(payload),
        )
        return self._unwrap_envelope(payload)

    @staticmethod
    def _merge_query_params(
        query_params: Mapping[str, object] | None,
        signing: SigningMaterial,
    ) -> dict[str, object]:
        merged = dict(query_params or {})
        merged.update(signing.query_params)
        return merged

    @staticmethod
    def _multipart_to_httpx(fields: Mapping[str, object] | None) -> list[tuple[str, tuple[None, str]]] | None:
        if fields is None:
            return None
        return [(key, (None, str(value))) for key, value in fields.items()]

    @staticmethod
    def _unwrap_envelope(payload: Any) -> APIEnvelope:
        if not isinstance(payload, dict) or "code" not in payload:
            return APIEnvelope(code=None, message=None, data=payload, raw=payload)

        code = payload.get("code")
        message = payload.get("msg")
        if code == 1002:
            raise SessionExpiredError(code=code, message=message or "Session expired", payload=payload)
        if code == 2160:
            raise CaptchaAnswerIncorrectError(
                code=code,
                message=message or "Wrong challenge answer",
                payload=payload,
            )
        if code == 2161:
            raise CaptchaRefreshRequiredError(
                code=code,
                message=message or "Challenge must be refreshed",
                payload=payload,
            )
        if code == 2162:
            raise VerificationCodeExpiredError(
                code=code,
                message=message or "Verification code expired",
                payload=payload,
            )
        if code != 0:
            raise APIError(code=code, message=message or "Unknown API error", payload=payload)

        if "data" in payload:
            data = payload.get("data")
        else:
            data = {key: value for key, value in payload.items() if key not in {"code", "msg"}}
            if not data:
                data = None

        return APIEnvelope(code=code, message=message, data=data, raw=payload)


def _mask(value: Any) -> str:
    """Keep the last four characters so log lines stay correlatable."""
    text = str(value)
    if len(text) <= 4:
        return _REDACTED
    return f"{_REDACTED}{text[-4:]}"


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS:
        return _REDACTED
    if lowered in _PARTIAL_KEYS and value is not None:
        return _mask(value)
    return _redact_payload(value)


def _redact_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_value(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item) for item in value)
    return value

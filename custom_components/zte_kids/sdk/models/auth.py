from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class CaptchaAnswer:
    kid: str
    jigsaw_code: str


@dataclass(frozen=True, slots=True)
class CaptchaChallenge:
    kid: str
    big_img: str | None = None
    small_img: str | None = None
    y_height: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CaptchaChallenge":
        return cls(
            kid=str(payload.get("kid", "")),
            big_img=payload.get("bigImg"),
            small_img=payload.get("smallImg"),
            y_height=_coerce_int(payload.get("yHeight")),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class Session:
    access_token: str
    openid: str
    token_expire_time: int | None = None
    user_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Session":
        return cls(
            access_token=str(payload.get("accesstoken", "")),
            openid=str(payload.get("openid", "")),
            token_expire_time=_coerce_int(payload.get("token_expire_time")),
            user_name=payload.get("userName"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class AccountProfile:
    openid: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None
    group_id: str | None = None
    account_status: int | None = None
    status: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AccountProfile":
        return cls(
            openid=str(payload.get("openid", "")),
            name=payload.get("name") or payload.get("userName"),
            phone=payload.get("phone"),
            email=payload.get("email"),
            avatar=payload.get("avator") or payload.get("avatar"),
            group_id=payload.get("groupid"),
            account_status=_coerce_int(payload.get("accountStatus") or payload.get("account_status")),
            status=_coerce_int(payload.get("status")),
            raw=payload,
        )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

"""Chat session model.

Sending a text message to a watch needs the routing identifiers the server
assigns to the conversation, which only ``api/chat/list`` returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: ``contentType`` for a plain text message, read from ``x2/e.A()``.
CONTENT_TYPE_TEXT = 101

#: ``userType`` identifying the sender as the account holder rather than the watch.
USER_TYPE_ACCOUNT = 1


@dataclass(frozen=True, slots=True)
class ChatSession:
    chat_id: str | None = None
    chat_type: int | None = None
    device_id: str | None = None
    group_id: str | None = None
    recv_id: str | None = None
    nickname: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ChatSession":
        return cls(
            chat_id=payload.get("chatID"),
            chat_type=_coerce_int(payload.get("chatType")),
            device_id=payload.get("deviceID"),
            group_id=payload.get("groupID"),
            recv_id=payload.get("recvID"),
            nickname=payload.get("nickname"),
            raw=dict(payload),
        )

    def matches(self, device_id: str) -> bool:
        """Whether this session addresses ``device_id``.

        ``deviceID`` is the reliable key; ``recvID`` is checked as a fallback
        because it carries the IMEI on some session shapes.
        """
        return device_id in {self.device_id, self.recv_id}


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

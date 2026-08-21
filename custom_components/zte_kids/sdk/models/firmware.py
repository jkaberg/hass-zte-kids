"""Firmware versions reported for a watch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    installed: str | None = None
    latest: str | None = None
    release_notes: str | None = None
    file_size: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "FirmwareInfo":
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            installed=payload.get("deviceFirmware"),
            latest=payload.get("firmware"),
            release_notes=payload.get("releaseNote"),
            file_size=payload.get("fileSize"),
            raw=dict(payload),
        )

    @property
    def update_available(self) -> bool:
        """Whether the service reports a newer build than the watch runs.

        Versions are opaque vendor strings, so this is a plain inequality
        rather than a version comparison — the service decides what is newer
        by what it offers.
        """
        if not self.installed or not self.latest:
            return False
        return self.installed.strip() != self.latest.strip()

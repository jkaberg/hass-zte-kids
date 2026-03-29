from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_POLLING,
    CONF_POLLING_ENABLED,
    CONF_POLLING_INTERVAL,
    DEFAULT_DEVICE_POLLING_ENABLED,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEVICE_POLLING_INTERVAL_MAX_SECONDS,
    DEVICE_POLLING_INTERVAL_MIN_SECONDS,
    DOMAIN,
)
from .sdk import SessionExpiredError, ZTEKidsClient
from .sdk.models import AccountProfile, Credentials, Device, DeviceSnapshot, Session

if TYPE_CHECKING:
    from . import ZTEKidsConfigEntry

LOGGER = logging.getLogger(__name__)
_UNSET = object()


@dataclass(slots=True)
class CoordinatorData:
    session: Session
    profile: AccountProfile
    devices: dict[str, DeviceSnapshot] = field(default_factory=dict)


class ZTEKidsDataUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        client: ZTEKidsClient,
        credentials: Credentials,
        config_entry: ZTEKidsConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_POLLING_INTERVAL,
        )
        self.client = client
        self.credentials = credentials
        self.config_entry = config_entry
        self._session: Session | None = None
        self._latest_data: CoordinatorData | None = None
        self._device_catalog: dict[str, Device] = {}
        self._device_last_polled_at: dict[str, float] = {}
        self._force_refresh = False
        self._update_polling_interval()

    def get_device(self, device_id: str) -> Device | None:
        if self._latest_data is not None:
            snapshot = self._latest_data.devices.get(device_id)
            if snapshot is not None:
                return snapshot.device
        return self._device_catalog.get(device_id)

    def device_polling_enabled(self, device_id: str) -> bool:
        value = self._device_polling_value(device_id, CONF_POLLING_ENABLED)
        if isinstance(value, bool):
            return value
        return DEFAULT_DEVICE_POLLING_ENABLED

    def device_polling_interval(self, device_id: str) -> int:
        fallback = DEFAULT_POLLING_INTERVAL_SECONDS
        value = self._device_polling_value(device_id, CONF_POLLING_INTERVAL)
        try:
            interval = int(value) if value is not None else fallback
        except (TypeError, ValueError):
            interval = fallback
        return min(
            DEVICE_POLLING_INTERVAL_MAX_SECONDS,
            max(DEVICE_POLLING_INTERVAL_MIN_SECONDS, interval),
        )

    async def async_set_device_polling_enabled(self, device_id: str, enabled: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options=self._updated_device_polling_options(device_id, enabled=enabled),
        )
        self._reschedule_polling()
        self.async_update_listeners()
        if enabled:
            self._force_refresh = True
            await self.async_request_refresh()

    async def async_set_device_polling_interval(self, device_id: str, interval_seconds: int) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options=self._updated_device_polling_options(
                device_id,
                interval_seconds=interval_seconds,
            ),
        )
        self._reschedule_polling()
        self.async_update_listeners()
        if self.device_polling_enabled(device_id):
            self._force_refresh = True
            await self.async_request_refresh()

    async def async_request_device_location_refresh(self, device_id: str) -> None:
        device = self.get_device(device_id)
        if device is None or not device.device_id:
            raise HomeAssistantError(f"Unknown ZTE Kids device: {device_id}")

        session = self._session
        if session is None and self._latest_data is not None:
            session = self._latest_data.session
        if session is None:
            raise HomeAssistantError("ZTE Kids session is not ready")

        try:
            response = await self.client.devices.request_location_refresh(
                session,
                device.device_id,
            )
        except Exception as exc:
            raise HomeAssistantError(
                f"Unable to request location refresh for {device.name or device.device_id}"
            ) from exc

        LOGGER.debug(
            "Requested ZTE Kids location refresh for device %s response=%s",
            device.device_id,
            response,
        )
        self._force_refresh = True
        await self.async_request_refresh()

    async def _async_update_data(self) -> CoordinatorData:
        try:
            if self._session is None:
                self._session = await self.client.auth.login(self.credentials)

            profile = await self.client.auth.query_profile(self._session)
            devices = await self.client.devices.list_related_devices(self._session)
            force_refresh = self._force_refresh
            self._force_refresh = False
            previous_snapshots = (
                dict(self._latest_data.devices) if self._latest_data is not None else {}
            )
            current_catalog: dict[str, Device] = {}
            now = monotonic()

            snapshots: dict[str, DeviceSnapshot] = {}
            for device in devices:
                if not device.device_id:
                    continue
                current_catalog[device.device_id] = device
                existing_snapshot = previous_snapshots.get(device.device_id)
                if not self._should_poll_device(
                    device.device_id,
                    now=now,
                    existing_snapshot=existing_snapshot,
                    force_refresh=force_refresh,
                ):
                    if existing_snapshot is not None:
                        snapshots[device.device_id] = replace(
                            existing_snapshot,
                            device=_merge_device_metadata(device, existing_snapshot.device),
                        )
                    LOGGER.debug(
                        "Skipping poll for device %s: enabled=%s interval=%ss",
                        device.device_id,
                        self.device_polling_enabled(device.device_id),
                        self.device_polling_interval(device.device_id),
                    )
                    continue
                try:
                    related_snapshot = DeviceSnapshot.from_payload(_device_to_payload(device))
                    if existing_snapshot is not None:
                        related_snapshot = _merge_related_snapshot(
                            related_snapshot,
                            existing_snapshot,
                            device=device,
                        )
                    else:
                        related_snapshot = replace(related_snapshot, device=device)
                    snapshots[device.device_id] = related_snapshot
                    self._device_last_polled_at[device.device_id] = now
                except Exception as exc:  # pragma: no cover - network boundary
                    LOGGER.debug("Failed to refresh device %s: %s", device.device_id, exc)
                    if existing_snapshot is not None:
                        snapshots[device.device_id] = replace(
                            existing_snapshot,
                            device=_merge_device_metadata(device, existing_snapshot.device),
                        )

            self._device_catalog = current_catalog
            self._device_last_polled_at = {
                device_id: polled_at
                for device_id, polled_at in self._device_last_polled_at.items()
                if device_id in current_catalog
            }
            data = CoordinatorData(session=self._session, profile=profile, devices=snapshots)
            self._latest_data = data
            self._update_polling_interval()
            return data
        except SessionExpiredError as exc:
            self._session = None
            raise ConfigEntryAuthFailed(
                "ZTE Kids session was invalidated; reauthentication is required"
            ) from exc
        except Exception as exc:  # pragma: no cover - network boundary
            raise UpdateFailed(str(exc)) from exc

    async def async_shutdown(self) -> None:
        return None

    def _device_polling_value(self, device_id: str, key: str) -> Any:
        device_polling = self.config_entry.options.get(CONF_DEVICE_POLLING, {})
        if not isinstance(device_polling, Mapping):
            return None
        device_options = device_polling.get(device_id, {})
        if not isinstance(device_options, Mapping):
            return None
        return device_options.get(key)

    def _updated_device_polling_options(
        self,
        device_id: str,
        *,
        enabled: object = _UNSET,
        interval_seconds: object = _UNSET,
    ) -> dict[str, Any]:
        options = dict(self.config_entry.options)
        device_polling = options.get(CONF_DEVICE_POLLING, {})
        normalized_device_polling = dict(device_polling) if isinstance(device_polling, Mapping) else {}
        current_options = normalized_device_polling.get(device_id, {})
        normalized_device_options = (
            dict(current_options) if isinstance(current_options, Mapping) else {}
        )

        if enabled is not _UNSET:
            normalized_device_options[CONF_POLLING_ENABLED] = bool(enabled)
        if interval_seconds is not _UNSET:
            normalized_device_options[CONF_POLLING_INTERVAL] = min(
                DEVICE_POLLING_INTERVAL_MAX_SECONDS,
                max(DEVICE_POLLING_INTERVAL_MIN_SECONDS, int(interval_seconds)),
            )

        normalized_device_polling[device_id] = normalized_device_options
        options[CONF_DEVICE_POLLING] = normalized_device_polling
        return options

    @callback
    def _update_polling_interval(self) -> None:
        interval_seconds = self._polling_update_interval_seconds()
        self.update_interval = (
            timedelta(seconds=interval_seconds) if interval_seconds is not None else None
        )

    @callback
    def _reschedule_polling(self) -> None:
        self._update_polling_interval()
        self._async_unsub_refresh()
        if self._listeners and self.update_interval is not None:
            self._schedule_refresh()

    def _polling_update_interval_seconds(self) -> int | None:
        device_ids = self._tracked_device_ids()
        if not device_ids:
            return DEFAULT_POLLING_INTERVAL_SECONDS

        enabled_intervals = [
            self.device_polling_interval(device_id)
            for device_id in device_ids
            if self.device_polling_enabled(device_id)
        ]
        if not enabled_intervals:
            return None
        return min(enabled_intervals)

    def _tracked_device_ids(self) -> tuple[str, ...]:
        if self._device_catalog:
            return tuple(self._device_catalog)
        if self._latest_data is not None and self._latest_data.devices:
            return tuple(self._latest_data.devices)

        device_polling = self.config_entry.options.get(CONF_DEVICE_POLLING, {})
        if isinstance(device_polling, Mapping):
            return tuple(str(device_id) for device_id in device_polling)
        return ()

    def _should_poll_device(
        self,
        device_id: str,
        *,
        now: float,
        existing_snapshot: DeviceSnapshot | None,
        force_refresh: bool,
    ) -> bool:
        if force_refresh:
            return True
        if existing_snapshot is None:
            return True
        if not self.device_polling_enabled(device_id):
            return False
        last_polled_at = self._device_last_polled_at.get(device_id)
        if last_polled_at is None:
            return True
        return (now - last_polled_at) >= self.device_polling_interval(device_id)


def _device_to_payload(device: Device) -> dict[str, Any]:
    if device.raw:
        return dict(device.raw)

    payload: dict[str, Any] = {"imei": device.device_id}
    if device.openid is not None:
        payload["openid"] = device.openid
    if device.name is not None:
        payload["name"] = device.name
    if device.relationship is not None:
        payload["relationship"] = device.relationship
    if device.model is not None:
        payload["model"] = device.model
    if device.group_id is not None:
        payload["groupid"] = device.group_id
    if device.single_group_id is not None:
        payload["single_groupid"] = device.single_group_id
    if device.is_admin is not None:
        payload["isAdmin"] = device.is_admin
    return payload


def _merge_related_snapshot(
    snapshot: DeviceSnapshot,
    previous_snapshot: DeviceSnapshot,
    *,
    device: Device,
) -> DeviceSnapshot:
    merged_raw = _merge_snapshot_payloads(previous_snapshot.raw, snapshot.raw)
    merged_snapshot = DeviceSnapshot.from_payload(merged_raw)
    return replace(
        merged_snapshot,
        device=_merge_device_metadata(device, previous_snapshot.device),
        battery_timestamp=(
            merged_snapshot.battery_timestamp
            if merged_snapshot.battery_timestamp is not None
            else previous_snapshot.battery_timestamp
        ),
        config=merged_snapshot.config or previous_snapshot.config,
    )


def _merge_snapshot_payloads(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in {"battery", "config", "lastLocation", "location"}
            and isinstance(merged.get(key), Mapping)
            and isinstance(value, Mapping)
        ):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
            continue
        merged[key] = value
    return merged


def _merge_device_metadata(primary: Device, secondary: Device) -> Device:
    return Device(
        device_id=primary.device_id or secondary.device_id,
        openid=primary.openid or secondary.openid,
        name=primary.name or secondary.name,
        relationship=primary.relationship or secondary.relationship,
        model=primary.model or secondary.model,
        group_id=primary.group_id or secondary.group_id,
        single_group_id=primary.single_group_id or secondary.single_group_id,
        is_admin=primary.is_admin if primary.is_admin is not None else secondary.is_admin,
        raw={**secondary.raw, **primary.raw},
    )

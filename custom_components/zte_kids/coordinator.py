from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COMMAND_COOLDOWN_SECONDS,
    CONF_DEVICE_POLLING,
    CONF_POLLING_ENABLED,
    CONF_POLLING_INTERVAL,
    DEFAULT_DEVICE_POLLING_ENABLED,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEVICE_POLLING_INTERVAL_MAX_SECONDS,
    DEVICE_POLLING_INTERVAL_MIN_SECONDS,
    DOMAIN,
    LOCATE_POLL_DELAYS_SECONDS,
    PUSH_KEEPALIVE_POLL_SECONDS,
    SLOW_REFRESH_SECONDS,
)
from .sdk import APIError, SessionExpiredError, ZTEKidsClient
from .sdk import commands
from .sdk.commands import Command
from .sdk.models import (
    AccountProfile,
    ChatSession,
    Credentials,
    Device,
    DeviceCapabilities,
    DeviceConfig,
    DeviceSnapshot,
    FirmwareInfo,
    GuardRule,
    Session,
    SportSummary,
)

if TYPE_CHECKING:
    from . import ZTEKidsConfigEntry

LOGGER = logging.getLogger(__name__)
_UNSET = object()

#: Service error codes that mean "the watch is not reachable right now".
#: 1153 is 设备离线 ("device offline"); 5001 is 设备未联网 ("device not on the
#: network, possibly poor signal or powered off"). Both are transient facts
#: about the watch, not problems with the request.
DEVICE_OFFLINE_CODES = frozenset({1153, 5001})

#: Service-facing names for the watch's internal feature permissions.
PERMISSION_COMMANDS = {
    "location": commands.CommandType.POSITION_PERMISSION,
    "battery": commands.CommandType.BATTERY_PERMISSION,
    "sms": commands.CommandType.SMS_PERMISSION,
    "activity": commands.CommandType.SPORTS_PERMISSION,
    "apps": commands.CommandType.APP_PERMISSION,
}


@dataclass(slots=True)
class CoordinatorData:
    session: Session
    profile: AccountProfile
    devices: dict[str, DeviceSnapshot] = field(default_factory=dict)
    sport: dict[str, SportSummary] = field(default_factory=dict)
    firmware: dict[str, FirmwareInfo] = field(default_factory=dict)
    guard_rules: dict[str, tuple[GuardRule, ...]] = field(default_factory=dict)
    unread: dict[str, int] = field(default_factory=dict)


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
        self._command_locks: dict[str, asyncio.Lock] = {}
        self._command_last_sent_at: dict[str, float] = {}
        self._chat_sessions: dict[str, ChatSession] = {}
        self._chat_uses_legacy: dict[str, bool] = {}
        self._relocate_tasks: dict[str, asyncio.Task[None]] = {}
        self._slow_refresh_at: float | None = None
        self._step_goals: dict[str, int] = {}
        self._mqtt: Any = None
        self._push_connected = False
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

    def device_capabilities(self, device_id: str) -> DeviceCapabilities:
        device = self.get_device(device_id)
        if device is None:
            return DeviceCapabilities()
        return DeviceCapabilities.from_payload(device.raw)

    def device_config(self, device_id: str) -> DeviceConfig:
        """The watch's own settings, as of the last config fetch.

        Config is only fetched on demand today; entities that read it must
        call :meth:`async_fetch_device_config` first.
        """
        if self._latest_data is None:
            return DeviceConfig()
        snapshot = self._latest_data.devices.get(device_id)
        if snapshot is None:
            return DeviceConfig()
        return DeviceConfig.from_payload(snapshot.config)

    async def _async_collect_extras(
        self,
        device_ids: list[str],
        *,
        now: float,
    ) -> dict[str, Any]:
        """Fetch the supplementary data sets that back the P3 entities.

        Anything here is strictly secondary to knowing where the watch is, so
        every fetch degrades to the previous value rather than failing the
        whole update.
        """
        previous = self._latest_data
        sport = dict(previous.sport) if previous else {}
        firmware = dict(previous.firmware) if previous else {}
        guard_rules = dict(previous.guard_rules) if previous else {}
        unread = dict(previous.unread) if previous else {}

        slow_due = (
            self._slow_refresh_at is None
            or (now - self._slow_refresh_at) >= SLOW_REFRESH_SECONDS
        )

        for device_id in device_ids:
            rows = await self._try(
                self.client.sport.query_daily(self._session, device_id),
                f"activity for {device_id}",
            )
            if slow_due:
                aim = await self._try(
                    self.client.sport.query_aim(self._session, device_id),
                    f"step goal for {device_id}",
                )
                if isinstance(aim, dict):
                    goal = _coerce_optional_int(aim.get("aim"))
                    if goal:
                        self._step_goals[device_id] = goal

            if rows is not None:
                sport[device_id] = SportSummary.from_rows(rows).with_goal(
                    self._step_goals.get(device_id)
                )

            if slow_due:
                payload = await self._try(
                    self.client.devices.query_firmware(self._session, device_id),
                    f"firmware for {device_id}",
                )
                if payload is not None:
                    firmware[device_id] = FirmwareInfo.from_payload(payload)

                rules = await self._try(
                    self.client.guard.list_rules(self._session, device_id),
                    f"safe zones for {device_id}",
                )
                if rules is not None:
                    parsed = [GuardRule.from_payload(rule) for rule in rules]
                    guard_rules[device_id] = tuple(r for r in parsed if r is not None)

        if device_ids:
            counts = await self._try(
                self.client.messages.unread_counts(self._session),
                "unread message counts",
            )
            if counts is not None:
                unread = _parse_unread(counts)

        if slow_due and device_ids:
            self._slow_refresh_at = now

        return {
            "sport": sport,
            "firmware": firmware,
            "guard_rules": guard_rules,
            "unread": unread,
        }

    async def _try(self, awaitable, what: str):
        """Await ``awaitable``, returning ``None`` if it fails.

        A session expiry still propagates: that needs re-authentication, not a
        shrug.
        """
        try:
            return await awaitable
        except SessionExpiredError:
            raise
        except Exception as exc:  # pragma: no cover - network boundary
            LOGGER.debug("Could not read %s: %s", what, exc)
            return None

    async def _async_read_config(
        self,
        device_id: str,
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """Read ``ConfigData`` during a poll.

        A config read failing must not lose the device: the watch's own
        settings are secondary to knowing where it is, so a failure keeps the
        previous config rather than propagating.
        """
        try:
            payload = await self.client.configuration.get_system_config(
                self._session, device_id
            )
        except SessionExpiredError:
            raise
        except Exception as exc:  # pragma: no cover - network boundary
            LOGGER.debug("Failed to read config for device %s: %s", device_id, exc)
            return dict(fallback)
        return dict(payload) if payload else dict(fallback)

    async def async_fetch_device_config(self, device_id: str) -> DeviceConfig:
        """Read ``ConfigData`` for one device and store it on its snapshot."""
        device = self._require_device(device_id)
        session = await self._async_session()
        try:
            payload = await self._with_session_retry(
                lambda active: self.client.configuration.get_system_config(
                    active, device.device_id
                ),
                session,
            )
        except Exception as exc:
            raise self._command_error(device, exc) from exc

        if self._latest_data is not None:
            snapshot = self._latest_data.devices.get(device_id)
            if snapshot is not None:
                self._latest_data.devices[device_id] = replace(snapshot, config=dict(payload))
                self.async_update_listeners()
        return DeviceConfig.from_payload(payload)

    async def async_send_command(
        self,
        device_id: str,
        command: Command,
        *,
        refresh: bool = False,
        cooldown: bool = True,
    ) -> None:
        """Send one command to a watch.

        Every write goes through here so that session recovery, per-device
        serialisation and error translation are implemented once. A successful
        return means the server accepted the command, not that the watch has
        acted on it.

        ``cooldown`` guards the one-shot actions — ring, restart, power off —
        where a repeated press is almost always a mis-tap. Configuration
        writes pass ``False``: a script legitimately sets several settings in
        a row, and rejecting that would be the wrong kind of safety.
        """
        device = self._require_device(device_id)

        async with self._device_lock(device_id):
            if cooldown:
                self._enforce_cooldown(device)
            session = await self._async_session()
            try:
                await self._with_session_retry(
                    lambda active: self.client.configuration.send_command(
                        active, device.device_id, command
                    ),
                    session,
                )
            except Exception as exc:
                raise self._command_error(device, exc) from exc

            self._command_last_sent_at[device_id] = monotonic()

        LOGGER.debug(
            "Sent ZTE Kids command type=%s to device %s",
            int(command.command_type),
            device.device_id,
        )

        if refresh:
            self._force_refresh = True
            await self.async_request_refresh()

    async def async_set_scheduled_power_off(
        self,
        device_id: str,
        *,
        enabled: bool | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> None:
        """Update the scheduled power-off window.

        The wire command carries the switch and both ends of the window
        together, so changing one field means resending the other two as they
        currently stand.
        """
        config = self.device_config(device_id)
        resolved_enabled = (
            config.scheduled_power_off if enabled is None else enabled
        ) or False
        resolved_start = start_time or config.scheduled_power_off_start
        resolved_end = end_time or config.scheduled_power_off_end
        if not resolved_start or not resolved_end:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_incomplete",
            )
        await self.async_send_command(
            device_id,
            commands.scheduled_power_off(
                enabled=resolved_enabled,
                start_time=resolved_start,
                end_time=resolved_end,
            ),
            refresh=True,
            cooldown=False,
        )

    async def async_set_shutdown_protection(
        self,
        device_id: str,
        *,
        enabled: bool | None = None,
        password: str | None = None,
    ) -> None:
        """Update shutdown protection. Status and password travel together."""
        config = self.device_config(device_id)
        resolved_enabled = (
            config.shutdown_protection.enabled if enabled is None else enabled
        ) or False
        resolved_password = (
            password if password is not None else config.shutdown_protection.password
        )
        await self.async_send_command(
            device_id,
            commands.shutdown_protection(
                enabled=resolved_enabled,
                password=resolved_password,
            ),
            refresh=True,
            cooldown=False,
        )

    async def async_set_step_goal(self, device_id: str, goal: int) -> None:
        """Set the watch's daily step target."""
        device = self._require_device(device_id)
        session = await self._async_session()
        try:
            await self._with_session_retry(
                lambda active: self.client.sport.set_aim(active, device.device_id, goal),
                session,
            )
        except Exception as exc:
            raise self._command_error(device, exc) from exc
        self._step_goals[device_id] = goal
        self.async_update_listeners()

    async def async_set_guard_rule_enabled(
        self,
        device_id: str,
        rule_id: str,
        enabled: bool,
    ) -> None:
        """Enable or disable one safe zone."""
        device = self._require_device(device_id)
        session = await self._async_session()
        try:
            await self._with_session_retry(
                lambda active: self.client.guard.set_rule_status(
                    active,
                    device_id=device.device_id,
                    security_guard_id=rule_id,
                    enabled=enabled,
                ),
                session,
            )
        except Exception as exc:
            raise self._command_error(device, exc) from exc
        # Safe zones are on the slow cadence; force the next poll to re-read them.
        self._slow_refresh_at = None
        self._force_refresh = True
        await self.async_request_refresh()

    def guard_rules(self, device_id: str) -> tuple[GuardRule, ...]:
        if self._latest_data is None:
            return ()
        return self._latest_data.guard_rules.get(device_id, ())

    def sport_summary(self, device_id: str) -> SportSummary:
        if self._latest_data is None:
            return SportSummary()
        return self._latest_data.sport.get(device_id, SportSummary())

    def firmware(self, device_id: str) -> FirmwareInfo:
        if self._latest_data is None:
            return FirmwareInfo()
        return self._latest_data.firmware.get(device_id, FirmwareInfo())

    async def async_set_task_reminder(
        self,
        device_id: str,
        *,
        enabled: bool | None = None,
        time: str | None = None,
    ) -> None:
        """Update the task reminder. Status and time travel together."""
        current = self.device_config(device_id).task_reminder
        resolved_enabled = (current.enabled if enabled is None else enabled) or False
        resolved_time = time or current.time
        payload: dict[str, Any] = {
            "reminderStatus": commands.bool_to_switch(resolved_enabled)
        }
        if resolved_time:
            payload["reminderTime"] = resolved_time
        await self.async_send_command(
            device_id,
            commands.nested(commands.CommandType.TASK_REMINDER, "taskReminderVO", payload),
            refresh=True,
            cooldown=False,
        )

    async def async_set_sos_numbers(
        self,
        device_id: str,
        numbers: tuple[str | None, str | None, str | None],
    ) -> None:
        """Set the whole SOS set in one write, as the wire format requires."""
        await self.async_send_command(
            device_id,
            commands.sos_numbers(numbers),
            refresh=True,
            cooldown=False,
        )

    async def async_set_permissions(
        self,
        device_id: str,
        permissions: Mapping[str, bool],
    ) -> None:
        """Set one or more of the watch's internal feature permissions.

        These are separate commands on the wire, so this is the one place that
        genuinely is a loop rather than a transaction.
        """
        for name, enabled in permissions.items():
            command_type = PERMISSION_COMMANDS.get(name)
            if command_type is None:
                continue
            await self.async_send_command(
                device_id,
                commands.switch(command_type, enabled),
                cooldown=False,
            )
        self._force_refresh = True
        await self.async_request_refresh()

    async def async_send_message(self, device_id: str, message: str) -> None:
        """Send a text message to a watch.

        Newer device families are reachable through TinyChat; older ones only
        through the legacy gateway. Whichever path works is remembered so the
        fallback is paid for once per device rather than on every send.
        """
        device = self._require_device(device_id)

        async with self._device_lock(device_id):
            self._enforce_cooldown(device)
            session = await self._async_session()

            if not self._chat_uses_legacy.get(device_id):
                try:
                    await self._async_send_message_modern(session, device, message)
                    self._command_last_sent_at[device_id] = monotonic()
                    return
                except ConfigEntryAuthFailed:
                    # An auth failure is not evidence that this device needs the
                    # legacy path; retrying there would only fail again.
                    raise
                except Exception as exc:
                    LOGGER.debug(
                        "TinyChat send failed for device %s, falling back to gateway: %s",
                        device.device_id,
                        exc,
                    )
                    self._chat_sessions.pop(device_id, None)

            # The modern attempt may have refreshed the session underneath us.
            session = await self._async_session()
            try:
                await self._with_session_retry(
                    lambda active: self.client.chat.send_text_legacy(
                        active, device.device_id, message
                    ),
                    session,
                )
            except Exception as exc:
                raise self._command_error(device, exc) from exc

            self._chat_uses_legacy[device_id] = True
            self._command_last_sent_at[device_id] = monotonic()

    async def _async_send_message_modern(
        self,
        session: Session,
        device: Device,
        message: str,
    ) -> None:
        chat_session = self._chat_sessions.get(device.device_id)
        if chat_session is None:
            sessions = await self._with_session_retry(
                lambda active: self.client.chat.list_sessions(active),
                session,
            )
            chat_session = next(
                (item for item in sessions if item.matches(device.device_id)),
                None,
            )
            if chat_session is None or not chat_session.chat_id:
                raise HomeAssistantError(
                    f"No chat conversation found for {device.name or device.device_id}"
                )
            self._chat_sessions[device.device_id] = chat_session

        await self._with_session_retry(
            lambda active: self.client.chat.send_text(active, chat_session, message),
            session,
        )

    async def async_refresh_device(self, device_id: str) -> None:
        """Re-read this watch's data from the API without waking the watch.

        Distinct from :meth:`async_request_device_location_refresh`, which asks
        the watch itself for a new position fix.
        """
        self._require_device(device_id)
        self._force_refresh = True
        await self.async_request_refresh()

    async def async_request_device_location_refresh(self, device_id: str) -> None:
        """Ask the watch for a fresh position fix.

        The endpoint only asks; the watch answers asynchronously and the app
        normally learns the result over MQTT. Polling once immediately would
        almost always read the previous fix, so the answer is polled for over
        a short bounded window instead.
        """
        device = self._require_device(device_id)

        async with self._device_lock(device_id):
            self._enforce_cooldown(device)
            session = await self._async_session()
            try:
                response = await self._with_session_retry(
                    lambda active: self.client.devices.request_location_refresh(
                        active, device.device_id
                    ),
                    session,
                )
            except Exception as exc:
                raise self._command_error(device, exc) from exc

            self._command_last_sent_at[device_id] = monotonic()

        LOGGER.debug(
            "Requested ZTE Kids location refresh for device %s response=%s",
            device.device_id,
            response,
        )

        self._force_refresh = True
        await self.async_request_refresh()
        self._schedule_locate_poll(device_id)

    @callback
    def _schedule_locate_poll(self, device_id: str) -> None:
        existing = self._relocate_tasks.pop(device_id, None)
        if existing is not None and not existing.done():
            existing.cancel()

        task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_poll_for_fix(device_id),
            name=f"{DOMAIN}_locate_{device_id}",
        )
        self._relocate_tasks[device_id] = task

    async def _async_poll_for_fix(self, device_id: str) -> None:
        """Re-poll a few times, stopping as soon as the fix timestamp moves."""
        baseline = self._location_timestamp(device_id)
        try:
            for delay in LOCATE_POLL_DELAYS_SECONDS:
                await asyncio.sleep(delay)
                self._force_refresh = True
                await self.async_request_refresh()
                current = self._location_timestamp(device_id)
                if current is not None and current != baseline:
                    LOGGER.debug(
                        "Fresh position fix for device %s after %ss", device_id, delay
                    )
                    return
        except asyncio.CancelledError:
            raise
        finally:
            self._relocate_tasks.pop(device_id, None)

    def _location_timestamp(self, device_id: str) -> int | None:
        if self._latest_data is None:
            return None
        snapshot = self._latest_data.devices.get(device_id)
        if snapshot is None or snapshot.location is None:
            return None
        return snapshot.location.timestamp

    def _require_device(self, device_id: str) -> Device:
        device = self.get_device(device_id)
        if device is None or not device.device_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_device",
                translation_placeholders={"device_id": device_id},
            )
        return device

    def _device_lock(self, device_id: str) -> asyncio.Lock:
        lock = self._command_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._command_locks[device_id] = lock
        return lock

    def _enforce_cooldown(self, device: Device) -> None:
        last_sent = self._command_last_sent_at.get(device.device_id)
        if last_sent is None:
            return
        elapsed = monotonic() - last_sent
        if elapsed >= COMMAND_COOLDOWN_SECONDS:
            return
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_too_soon",
            translation_placeholders={
                "device": device.name or device.device_id,
                "seconds": str(int(COMMAND_COOLDOWN_SECONDS - elapsed) + 1),
            },
        )

    async def _async_session(self) -> Session:
        if self._session is not None:
            return self._session
        if self._latest_data is not None:
            self._session = self._latest_data.session
            return self._session
        try:
            self._session = await self.client.auth.login(self.credentials)
        except Exception as exc:
            raise ConfigEntryAuthFailed(
                "ZTE Kids session is not available and re-authentication failed"
            ) from exc
        return self._session

    async def _with_session_retry(self, action, session: Session):
        """Run ``action`` and re-login once if the session was invalidated.

        The phone app invalidates our session whenever it logs in, so a command
        racing that is routine rather than exceptional.
        """
        try:
            return await action(session)
        except SessionExpiredError:
            LOGGER.debug("ZTE Kids session expired mid-command; re-authenticating")
            self._session = None
            try:
                refreshed = await self.client.auth.login(self.credentials)
            except Exception as exc:
                raise ConfigEntryAuthFailed(
                    "ZTE Kids session was invalidated; reauthentication is required"
                ) from exc
            self._session = refreshed
            return await action(refreshed)

    def _command_error(self, device: Device, exc: Exception) -> Exception:
        if isinstance(exc, (HomeAssistantError, ConfigEntryAuthFailed)):
            return exc

        if isinstance(exc, APIError) and exc.code in DEVICE_OFFLINE_CODES:
            # The watch being switched off or out of coverage is a normal,
            # user-actionable situation, not an integration failure. Reporting
            # it as one gives the caller a 500 and a stack trace, and leaks the
            # service's untranslated Chinese message into the UI.
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_offline",
                translation_placeholders={"device": device.name or device.device_id},
            )

        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={
                "device": device.name or device.device_id,
                "error": str(exc),
            },
        )

    async def _async_update_data(self) -> CoordinatorData:
        try:
            if self._session is None:
                self._session = await self.client.auth.login(self.credentials)

            if self._latest_data is None or self._latest_data.session != self._session:
                profile = await self.client.auth.query_profile(self._session)
            else:
                profile = self._latest_data.profile
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
                    config = await self._async_read_config(
                        device.device_id,
                        fallback=existing_snapshot.config if existing_snapshot else {},
                    )
                    snapshots[device.device_id] = replace(related_snapshot, config=config)
                    self._device_last_polled_at[device.device_id] = now
                except Exception as exc:  # pragma: no cover - network boundary
                    LOGGER.debug("Failed to refresh device %s: %s", device.device_id, exc)
                    if existing_snapshot is not None:
                        snapshots[device.device_id] = replace(
                            existing_snapshot,
                            device=_merge_device_metadata(device, existing_snapshot.device),
                        )

            polled_ids = [
                device_id
                for device_id in snapshots
                if self._device_last_polled_at.get(device_id) == now
            ]
            extras = await self._async_collect_extras(polled_ids, now=now)

            self._device_catalog = current_catalog
            self._device_last_polled_at = {
                device_id: polled_at
                for device_id, polled_at in self._device_last_polled_at.items()
                if device_id in current_catalog
            }
            data = CoordinatorData(
                session=self._session,
                profile=profile,
                devices=snapshots,
                **extras,
            )
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

    # ---- real-time push ----

    @property
    def session(self) -> Session | None:
        if self._session is not None:
            return self._session
        return self._latest_data.session if self._latest_data else None

    def group_ids(self) -> list[str]:
        """Chat-group ids for every tracked device, for topic subscription."""
        ids: list[str] = []
        for device_id in (self._latest_data.devices if self._latest_data else {}):
            device = self.get_device(device_id)
            if device is not None and device.group_id:
                ids.append(device.group_id)
        for device in self._device_catalog.values():
            if device.group_id and device.group_id not in ids:
                ids.append(device.group_id)
        return ids

    @property
    def push_connected(self) -> bool:
        return self._push_connected

    @callback
    def async_set_push_connected(self, connected: bool) -> None:
        if self._push_connected == connected:
            return
        self._push_connected = connected
        # A dropped stream must fall back to the normal polling cadence.
        self._reschedule_polling()
        self.async_update_listeners()

    @callback
    def async_apply_push_snapshot(self, device_id: str, snapshot: DeviceSnapshot) -> None:
        """Apply a pushed value straight to a device's state."""
        data = self._latest_data
        if data is None or device_id not in data.devices:
            return
        data.devices[device_id] = snapshot
        self.async_set_updated_data(data)

    @callback
    def async_schedule_push_refresh(self) -> None:
        """Read state after an event that only said "something changed"."""
        self._force_refresh = True
        self.config_entry.async_create_background_task(
            self.hass,
            self.async_request_refresh(),
            name=f"{DOMAIN}_push_refresh",
        )

    @callback
    def async_push_session_invalidated(self) -> None:
        """The account signed in elsewhere, so our token is dead."""
        self._session = None
        self.config_entry.async_start_reauth(self.hass)

    async def async_shutdown(self) -> None:
        for task in list(self._relocate_tasks.values()):
            task.cancel()
        self._relocate_tasks.clear()
        await super().async_shutdown()

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

        if self._push_connected:
            # Events carry the changes; polling stays on only as a safety net
            # in case the stream dies quietly.
            return PUSH_KEEPALIVE_POLL_SECONDS

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


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_unread(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        device_id = row.get("imei") or row.get("deviceId")
        if not device_id:
            continue
        value = _coerce_optional_int(
            row.get("num") if row.get("num") is not None else row.get("unreadNum")
        )
        counts[str(device_id)] = value or 0
    return counts

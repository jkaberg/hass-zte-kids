"""Real-time event routing.

Translates broker events into coordinator state. Events that carry a usable
value are applied directly; the rest only announce that something changed, so
the correct response is to go and read it.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

from .const import EVENT_MESSAGE, EVENT_SAFE_ZONE
from .sdk.models import DeviceLocation
from .sdk.mqtt import MqttBridge, MqttEvent, build_topics

if TYPE_CHECKING:
    from .coordinator import ZTEKidsDataUpdateCoordinator

LOGGER = logging.getLogger(__name__)

#: Carries a full position fix.
LOCATION_EVENT = "deviceNowLocation"

#: Carries a battery percentage.
BATTERY_EVENT = "electricity"

#: Announce that state changed without carrying the new value.
REFRESH_EVENTS = frozenset({"watchSetting", "SynDone"})

#: Chat and SMS traffic, surfaced on the Home Assistant bus.
MESSAGE_EVENTS = frozenset(
    {
        "sms",
        "chatGroupMessage",
        "singleGroupMessage",
        "api_messageVoice",
        "api_singleMessageVoice",
    }
)

SAFE_ZONE_EVENT = "securityGuard"
ACCOUNT_EVENT = "accountMessage"


class ZTEKidsPushManager:
    """Owns the broker connection and applies what it delivers."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ZTEKidsDataUpdateCoordinator,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._bridge: MqttBridge | None = None

    @property
    def connected(self) -> bool:
        return bool(self._bridge is not None and self._bridge.connected)

    async def async_start(self) -> None:
        """Open the stream. Raises if the broker cannot be reached."""
        session = self.coordinator.session
        if session is None or not session.openid:
            LOGGER.debug("No session yet; not opening the event stream")
            return

        config = self.coordinator.client.environment.mqtt
        topics = build_topics(config, session.openid, self.coordinator.group_ids())

        bridge = MqttBridge(
            config=config,
            openid=session.openid,
            on_event=self._dispatch,
            on_connection_change=self._dispatch_connection_change,
        )
        await self.hass.async_add_executor_job(bridge.start, topics)
        self._bridge = bridge
        LOGGER.debug("Event stream started on %s", topics)

    async def async_stop(self) -> None:
        bridge, self._bridge = self._bridge, None
        if bridge is None:
            return
        try:
            await self.hass.async_add_executor_job(bridge.stop)
        except Exception:  # pragma: no cover - network boundary
            LOGGER.debug("Event stream did not close cleanly", exc_info=True)

    # ---- thread hand-off ----

    def _dispatch(self, event: MqttEvent) -> None:
        """Called on paho's thread; hop to the event loop before touching state."""
        self.hass.loop.call_soon_threadsafe(self._handle_event, event)

    def _dispatch_connection_change(self, connected: bool) -> None:
        self.hass.loop.call_soon_threadsafe(
            self.coordinator.async_set_push_connected, connected
        )

    # ---- routing, on the event loop ----

    @callback
    def _handle_event(self, event: MqttEvent) -> None:
        LOGGER.debug("Push event %s from %s", event.type, event.topic)

        if event.type == LOCATION_EVENT:
            self._apply_location(event)
        elif event.type == BATTERY_EVENT:
            self._apply_battery(event)
        elif event.type in REFRESH_EVENTS:
            self.coordinator.async_schedule_push_refresh()
        elif event.type in MESSAGE_EVENTS:
            self._fire(EVENT_MESSAGE, event)
        elif event.type == SAFE_ZONE_EVENT:
            self._fire(EVENT_SAFE_ZONE, event)
            self.coordinator.async_schedule_push_refresh()
        elif event.type == ACCOUNT_EVENT:
            self._handle_account_message(event)

    def _apply_location(self, event: MqttEvent) -> None:
        snapshot = self._snapshot(event)
        if snapshot is None:
            return
        location = DeviceLocation.from_payload(event.payload)
        if location is None:
            return
        self.coordinator.async_apply_push_snapshot(
            event.device_id, replace(snapshot, location=location)
        )

    def _apply_battery(self, event: MqttEvent) -> None:
        snapshot = self._snapshot(event)
        if snapshot is None:
            return
        raw = event.payload.get("electricity")
        if raw is None:
            # Some builds announce the change without the value.
            self.coordinator.async_schedule_push_refresh()
            return
        try:
            battery = int(raw)
        except (TypeError, ValueError):
            return
        self.coordinator.async_apply_push_snapshot(
            event.device_id, replace(snapshot, battery=battery)
        )

    def _snapshot(self, event: MqttEvent):
        """The snapshot this event belongs to, if it is one of ours.

        The account topic is per-account, not per-device, so an event for a
        device this entry does not track is ignored rather than trusted.
        """
        device_id = event.device_id
        if not device_id:
            return None
        data = self.coordinator.data
        if data is None:
            return None
        snapshot = data.devices.get(device_id)
        if snapshot is None:
            LOGGER.debug("Ignoring a push event for an untracked device")
            return None
        return snapshot

    def _handle_account_message(self, event: MqttEvent) -> None:
        message = event.payload.get("message")
        subtype = message.get("type") if isinstance(message, dict) else None
        if subtype == "LoginOffLine":
            LOGGER.warning(
                "The ZTE Kids account signed in elsewhere; this session is now invalid"
            )
            self.coordinator.async_push_session_invalidated()

    def _fire(self, event_name: str, event: MqttEvent) -> None:
        self.hass.bus.async_fire(
            event_name,
            {
                "device_id": event.device_id,
                "type": event.type,
                "data": event.payload,
            },
        )

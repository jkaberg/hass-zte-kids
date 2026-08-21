"""Real-time event stream.

The app keeps one MQTT connection open and receives location, battery, SOS and
chat events as they happen rather than polling for them. This replicates that:
the same broker, the same topic strategy, the same duplicate suppression.

Everything here is best-effort. The broker is a third-party production service
whose credentials are shared by every copy of the app, and it can change or
disappear without notice, so any failure must degrade to HTTP polling rather
than break the integration.

Decoding is kept as free functions over bytes so it can be tested without a
broker; :class:`MqttBridge` is the only part that needs a network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import json
import logging
import random
import threading
from time import monotonic
from typing import Any

from .config import MqttConfig

LOGGER = logging.getLogger(__name__)

#: The app ignores a payload identical to the previous one within this window.
DUPLICATE_WINDOW_SECONDS = 3.0

#: QoS used for every subscription, matching the app.
QOS = 0


@dataclass(frozen=True, slots=True)
class MqttEvent:
    """One decoded broker message."""

    topic: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def device_id(self) -> str | None:
        value = self.payload.get("imei") or self.payload.get("deviceId")
        return str(value) if value else None


def account_topic(config: MqttConfig, openid: str) -> str:
    """The topic carrying this account's device events."""
    return f"{config.client_prefix}/user/{openid}"


def group_topic(config: MqttConfig, group_id: str) -> str:
    """The topic carrying one device group's chat traffic."""
    return f"{config.client_prefix}/chatGroup/{group_id}"


def build_topics(config: MqttConfig, openid: str, group_ids: Iterable[str]) -> list[str]:
    """The account topic plus one topic per device group.

    Subscription is not per-IMEI: device events arrive on the account topic and
    the per-group chat topics. No wildcards — this connection has no business
    seeing anyone else's traffic.
    """
    topics = [account_topic(config, openid)]
    seen: set[str] = set()
    for group_id in group_ids:
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        topics.append(group_topic(config, group_id))
    return topics


def build_client_id(openid: str, config: MqttConfig) -> str:
    """Build a client id in the app's shape.

    The random tail must stay wide: a collision with the phone app's client id
    would make both connections fight for the same session and flap.
    """
    prefix = (openid or "")[:8]
    suffix = "".join(str(random.randint(0, 9999999)) for _ in range(3))
    return f"{config.client_id_prefix}{prefix}{suffix}"


def decode_message(topic: str, payload: bytes) -> MqttEvent | None:
    """Decode one raw broker message, or ``None`` if it is not usable."""
    try:
        text = payload.decode("utf-8")
    except (AttributeError, UnicodeDecodeError):
        LOGGER.debug("Dropping a message that was not UTF-8 text")
        return None

    try:
        body = json.loads(text)
    except ValueError:
        LOGGER.debug("Dropping a message that was not JSON")
        return None

    if not isinstance(body, dict):
        return None

    event_type = body.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None

    return MqttEvent(topic=topic, type=event_type, payload=body)


class MqttBridge:
    """A thin wrapper over paho-mqtt.

    paho is not asyncio-native and runs its own network thread, so every
    callback hands straight off to the caller instead of touching Home
    Assistant state itself.
    """

    def __init__(
        self,
        *,
        config: MqttConfig,
        openid: str,
        on_event: Callable[[MqttEvent], None],
        on_connection_change: Callable[[bool], None] | None = None,
    ) -> None:
        self._config = config
        self._openid = openid
        self._on_event = on_event
        self._on_connection_change = on_connection_change
        self._client: Any = None
        self._topics: list[str] = []
        self._last_payload: bytes | None = None
        self._last_payload_at: float = 0.0
        self._lock = threading.Lock()
        self._connected = threading.Event()

    @property
    def connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected())

    def wait_connected(self, timeout: float) -> bool:
        """Block until the broker acknowledges the connection, or give up.

        Returning ``False`` is not fatal: paho keeps retrying in the
        background, and the caller keeps polling until it succeeds.
        """
        return self._connected.wait(timeout)

    def start(self, topics: Iterable[str]) -> None:
        """Begin connecting and subscribe once the broker answers.

        Returns immediately. Connecting happens on paho's own thread so an
        unreachable broker cannot stall Home Assistant's startup, and paho
        retries on its own for as long as the client is alive.
        """
        import paho.mqtt.client as mqtt

        self._topics = list(topics)
        client_id = build_client_id(self._openid, self._config)

        # paho 2.x requires an explicit callback API version. Home Assistant
        # core still constrains paho to 1.6.1, so both have to work.
        if hasattr(mqtt, "CallbackAPIVersion"):
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                clean_session=True,
            )
        else:  # pragma: no cover - depends on the installed paho
            client = mqtt.Client(client_id=client_id, clean_session=True)

        client.username_pw_set(self._config.username, self._config.password)
        client.on_connect = self._handle_connect
        client.on_disconnect = self._handle_disconnect
        client.on_message = self._handle_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)

        self._client = client
        LOGGER.debug(
            "Connecting to %s:%s as %s", self._config.host, self._config.port, client_id
        )
        client.connect_async(self._config.host, self._config.port, keepalive=60)
        client.loop_start()

    def stop(self) -> None:
        """Stop the network loop and close. Blocking — call from an executor."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.disconnect()
        finally:
            client.loop_stop()

    # ---- paho callbacks, all on paho's own thread ----

    def _handle_connect(
        self, client: Any, userdata: Any, flags: Any, rc: Any, *args: Any
    ) -> None:
        if rc != 0:
            LOGGER.warning("Broker refused the connection (code %s)", rc)
            return
        if self._topics:
            LOGGER.debug("Subscribing to %s", self._topics)
            client.subscribe([(topic, QOS) for topic in self._topics])
        self._connected.set()
        if self._on_connection_change is not None:
            self._on_connection_change(True)

    def _handle_disconnect(self, client: Any, userdata: Any, rc: Any, *args: Any) -> None:
        LOGGER.debug("Disconnected from broker (code %s); paho will retry", rc)
        self._connected.clear()
        if self._on_connection_change is not None:
            self._on_connection_change(False)

    def _handle_message(self, client: Any, userdata: Any, message: Any) -> None:
        payload = getattr(message, "payload", None)
        if payload is None or self._is_duplicate(payload):
            return

        event = decode_message(getattr(message, "topic", ""), payload)
        if event is None:
            return

        try:
            self._on_event(event)
        except Exception:  # pragma: no cover - defensive; paho swallows anyway
            LOGGER.exception("Event handler raised")

    def _is_duplicate(self, payload: bytes) -> bool:
        """Suppress an identical payload repeated within the window.

        The app does the same, which suggests the broker really does redeliver.
        """
        now = monotonic()
        with self._lock:
            duplicate = (
                payload == self._last_payload
                and (now - self._last_payload_at) < DUPLICATE_WINDOW_SECONDS
            )
            self._last_payload = payload
            self._last_payload_at = now
        return duplicate

"""Push event decoding and routing.

The broker connection itself cannot be exercised offline. What can be — and
what actually carries the risk — is the decoding, the topic strategy, and the
routing of each event type onto coordinator state.
"""

from __future__ import annotations

import json
from time import monotonic
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import (
    CONF_ENABLE_PUSH,
    DOMAIN,
    EVENT_MESSAGE,
    EVENT_SAFE_ZONE,
    FACET_LOCATION,
    FRESHNESS_FACETS,
    MIN_POLL_SCHEDULE_SECONDS,
    PUSH_CONNECT_TIMEOUT_SECONDS,
)
from custom_components.zte_kids.coordinator import (
    CoordinatorData,
    ZTEKidsDataUpdateCoordinator,
)
from custom_components.zte_kids.push import ZTEKidsPushManager
from custom_components.zte_kids.sdk.config import ENVIRONMENTS, Environment
from custom_components.zte_kids.sdk.models import (
    AccountProfile,
    Credentials,
    Device,
    DeviceSnapshot,
    Session,
)
from custom_components.zte_kids.sdk.mqtt import (
    MqttEvent,
    account_topic,
    build_client_id,
    build_topics,
    decode_message,
    group_topic,
)

MQTT = ENVIRONMENTS[Environment.PRODUCTION].mqtt
TOPIC = "watchiot/user/openid-1"


# ---- topics and identity ----


def test_topics_are_scoped_to_this_account() -> None:
    assert account_topic(MQTT, "openid-1") == "watchiot/user/openid-1"
    assert group_topic(MQTT, "group-1") == "watchiot/chatGroup/group-1"


def test_subscriptions_cover_the_account_and_each_group_once() -> None:
    topics = build_topics(MQTT, "openid-1", ["group-1", "group-2", "group-1", ""])

    assert topics == [
        "watchiot/user/openid-1",
        "watchiot/chatGroup/group-1",
        "watchiot/chatGroup/group-2",
    ]
    # A wildcard here would pull in other people's traffic.
    assert not any("#" in topic or "+" in topic for topic in topics)


def test_client_id_keeps_the_app_shape_but_randomises() -> None:
    first = build_client_id("openid-abcdefghij", MQTT)
    second = build_client_id("openid-abcdefghij", MQTT)

    assert first.startswith("GID_LKY@@@openid-a")
    # A collision with the phone app's id would make both connections flap.
    assert first != second


# ---- decoding ----


@pytest.mark.parametrize(
    "payload",
    [b"\xff\xfe", b"not json", b"[1,2,3]", b'{"no":"type"}', b'{"type":""}'],
)
def test_decode_rejects_junk(payload: bytes) -> None:
    assert decode_message(TOPIC, payload) is None


def test_decode_extracts_type_and_device() -> None:
    event = decode_message(
        TOPIC, json.dumps({"type": "deviceNowLocation", "imei": "imei-1"}).encode()
    )

    assert event is not None
    assert event.type == "deviceNowLocation"
    assert event.device_id == "imei-1"


def test_decode_falls_back_to_the_alternate_device_key() -> None:
    event = decode_message(TOPIC, json.dumps({"type": "sms", "deviceId": "imei-9"}).encode())

    assert event is not None
    assert event.device_id == "imei-9"


# ---- routing ----


def _coordinator(hass) -> ZTEKidsDataUpdateCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.environment = ENVIRONMENTS[Environment.PRODUCTION]
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=client,
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=entry,
    )
    data = CoordinatorData(
        session=Session(access_token="token", openid="openid-1"),
        profile=AccountProfile(openid="openid-1"),
        devices={
            "imei-1": DeviceSnapshot(
                device=Device(device_id="imei-1", name="Watch 1", group_id="group-1"),
                battery=50,
                raw={"imei": "imei-1"},
            )
        },
    )
    coordinator.async_set_updated_data(data)
    coordinator._latest_data = data
    return coordinator


def _event(event_type: str, payload: dict) -> MqttEvent:
    return MqttEvent(topic=TOPIC, type=event_type, payload=payload)


@pytest.mark.asyncio
async def test_location_event_updates_the_tracker(hass) -> None:
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(
        _event("deviceNowLocation", {"imei": "imei-1", "lat": 59.91, "lon": 10.75, "radius": 25})
    )

    location = coordinator.data.devices["imei-1"].location
    assert location is not None
    assert location.latitude == 59.91
    assert location.longitude == 10.75
    assert location.radius == 25


@pytest.mark.asyncio
async def test_battery_event_updates_the_sensor(hass) -> None:
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(_event("electricity", {"imei": "imei-1", "electricity": 17}))

    assert coordinator.data.devices["imei-1"].battery == 17


@pytest.mark.asyncio
async def test_a_battery_event_without_a_value_triggers_a_read(hass) -> None:
    """Being told something changed is not the same as being told the value."""
    coordinator = _coordinator(hass)
    coordinator.async_schedule_push_refresh = MagicMock()
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(_event("electricity", {"imei": "imei-1"}))

    coordinator.async_schedule_push_refresh.assert_called_once()
    assert coordinator.data.devices["imei-1"].battery == 50


@pytest.mark.asyncio
async def test_state_events_trigger_a_read_rather_than_a_guess(hass) -> None:
    coordinator = _coordinator(hass)
    coordinator.async_schedule_push_refresh = MagicMock()
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(_event("watchSetting", {"imei": "imei-1", "scene": 1}))

    coordinator.async_schedule_push_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_events_for_untracked_devices_are_ignored(hass) -> None:
    """The account topic is shared by every device on the account."""
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(
        _event("deviceNowLocation", {"imei": "someone-elses-watch", "lat": 1.0, "lon": 2.0})
    )

    assert coordinator.data.devices["imei-1"].location is None


@pytest.mark.asyncio
async def test_message_and_safe_zone_events_reach_the_bus(hass) -> None:
    coordinator = _coordinator(hass)
    coordinator.async_schedule_push_refresh = MagicMock()
    push = ZTEKidsPushManager(hass, coordinator)

    seen: list[tuple[str, dict]] = []
    hass.bus.async_listen(EVENT_SAFE_ZONE, lambda e: seen.append(("zone", e.data)))
    hass.bus.async_listen(EVENT_MESSAGE, lambda e: seen.append(("message", e.data)))

    push._handle_event(_event("securityGuard", {"imei": "imei-1", "scene": 1, "topic": 2}))
    push._handle_event(
        _event("singleGroupMessage", {"imei": "imei-1", "message": {"content": "hi"}})
    )
    await hass.async_block_till_done()

    assert [name for name, _ in seen] == ["zone", "message"]
    assert seen[0][1]["device_id"] == "imei-1"
    assert seen[1][1]["type"] == "singleGroupMessage"


@pytest.mark.asyncio
async def test_forced_logout_triggers_reauth(hass) -> None:
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)
    coordinator.config_entry.async_start_reauth = MagicMock()

    push._handle_event(_event("accountMessage", {"message": {"type": "LoginOffLine"}}))

    coordinator.config_entry.async_start_reauth.assert_called_once()


@pytest.mark.asyncio
async def test_unrecognised_events_are_ignored(hass) -> None:
    coordinator = _coordinator(hass)
    coordinator.async_schedule_push_refresh = MagicMock()
    push = ZTEKidsPushManager(hass, coordinator)

    push._handle_event(_event("somethingNewFromTheVendor", {"imei": "imei-1"}))

    coordinator.async_schedule_push_refresh.assert_not_called()


# ---- lifecycle ----


@pytest.mark.asyncio
async def test_start_subscribes_to_the_account_and_group_topics(hass, monkeypatch) -> None:
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)

    started: list[list[str]] = []

    class FakeBridge:
        def __init__(self, **kwargs):
            self.connected = False

        def start(self, topics):
            started.append(list(topics))

        def wait_connected(self, timeout):
            return True

        def stop(self):
            pass

    monkeypatch.setattr("custom_components.zte_kids.push.MqttBridge", FakeBridge)
    await push.async_start()

    assert started == [["watchiot/user/openid-1", "watchiot/chatGroup/group-1"]]


@pytest.mark.asyncio
async def test_push_does_not_connect_unless_it_is_turned_on(hass) -> None:
    """Setup must not open a broker connection by default."""
    from custom_components.zte_kids import _async_start_push

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_USERNAME: "u", CONF_PASSWORD: "p"}, options={}
    )
    entry.add_to_hass(hass)
    entry.runtime_data = MagicMock()
    entry.runtime_data.push = None

    await _async_start_push(hass, entry)

    assert entry.runtime_data.push is None


@pytest.mark.asyncio
async def test_a_broker_that_refuses_us_leaves_polling_alone(hass, monkeypatch) -> None:
    from custom_components.zte_kids import _async_start_push

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p"},
        options={CONF_ENABLE_PUSH: True},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = MagicMock()
    entry.runtime_data.push = None
    entry.runtime_data.coordinator = _coordinator(hass)

    class ExplodingManager:
        def __init__(self, *args, **kwargs):
            pass

        async def async_start(self):
            raise OSError("broker unreachable")

    monkeypatch.setattr(
        "custom_components.zte_kids.push.ZTEKidsPushManager", ExplodingManager
    )
    await _async_start_push(hass, entry)

    # Polling carries on regardless.
    assert entry.runtime_data.push is None


@pytest.mark.asyncio
async def test_stopping_closes_the_bridge(hass, monkeypatch) -> None:
    coordinator = _coordinator(hass)
    push = ZTEKidsPushManager(hass, coordinator)
    bridge = MagicMock()
    push._bridge = bridge

    await push.async_stop()

    bridge.stop.assert_called_once()
    assert push._bridge is None


@pytest.mark.asyncio
async def test_connection_state_never_changes_the_polling_cadence(hass) -> None:
    """Connecting is not evidence of anything; only delivered data is.

    A broker can accept a connection and then stay silent, which is what makes
    connection state a dangerous thing to schedule on: it looks identical to a
    healthy stream while the child's position quietly goes hours stale.
    """
    coordinator = _coordinator(hass)
    coordinator.async_request_refresh = AsyncMock()
    before = coordinator.update_interval

    coordinator.async_set_push_connected(True)
    assert coordinator.update_interval == before

    coordinator.async_set_push_connected(False)
    assert coordinator.push_connected is False
    assert coordinator.update_interval == before


@pytest.mark.asyncio
async def test_a_broker_that_never_answers_leaves_polling_at_full_rate(
    hass, monkeypatch
) -> None:
    """Missing the connect deadline is not a failure, just a slower start.

    paho keeps retrying underneath, so the stream can still come up later; what
    must not happen is polling slowing down for a stream that is not there.
    """
    coordinator = _coordinator(hass)
    manager = ZTEKidsPushManager(hass, coordinator)
    before = coordinator.update_interval

    waited: list[float] = []

    class SilentBridge:
        def __init__(self, **kwargs):
            self.connected = False

        def start(self, topics):
            pass

        def wait_connected(self, timeout):
            waited.append(timeout)
            return False

        def stop(self):
            pass

    monkeypatch.setattr("custom_components.zte_kids.push.MqttBridge", SilentBridge)
    await manager.async_start()

    assert waited == [PUSH_CONNECT_TIMEOUT_SECONDS]
    assert coordinator.push_connected is False
    assert coordinator.update_interval == before


@pytest.mark.asyncio
async def test_a_delivered_fix_defers_the_next_poll(hass) -> None:
    """A location event satisfies the location facet, so the poll can wait."""
    coordinator = _coordinator(hass)
    interval = coordinator.device_polling_interval("imei-1")
    now = monotonic()
    coordinator._mark_fresh("imei-1", FRESHNESS_FACETS, now)
    coordinator._mark_fresh("imei-1", (FACET_LOCATION,), now - interval + 5)
    coordinator._update_polling_interval()

    # The fix on file is about to go stale, so a poll is imminent.
    assert coordinator.update_interval.total_seconds() <= MIN_POLL_SCHEDULE_SECONDS

    push = ZTEKidsPushManager(hass, coordinator)
    push._handle_event(
        _event("deviceNowLocation", {"imei": "imei-1", "lat": 59.91, "lon": 10.75})
    )

    # The event delivered what the poll was going to fetch, so the deadline
    # moved out by a full interval and no request was made.
    assert coordinator.facet_ages("imei-1")["location"] < 1
    assert coordinator.update_interval.total_seconds() > interval / 2


@pytest.mark.asyncio
async def test_a_silent_stream_polls_at_the_configured_rate(hass) -> None:
    """The regression: a connected but silent broker must not slow polling.

    Being subscribed is not evidence of delivery, so nothing about it is
    allowed to stretch the interval past what the user asked for.
    """
    coordinator = _coordinator(hass)
    interval = coordinator.device_polling_interval("imei-1")
    coordinator._mark_fresh("imei-1", FRESHNESS_FACETS, monotonic())
    coordinator.async_set_push_connected(True)
    coordinator._update_polling_interval()

    assert coordinator.update_interval.total_seconds() == pytest.approx(interval, abs=1)


@pytest.mark.asyncio
async def test_events_for_one_watch_do_not_starve_another(hass) -> None:
    """Deadlines are per watch, so a chatty one cannot hold up a quiet one."""
    coordinator = _coordinator(hass)
    coordinator.data.devices["imei-2"] = DeviceSnapshot(
        device=Device(device_id="imei-2", name="Watch 2", group_id="group-2"),
        raw={"imei": "imei-2"},
    )
    now = monotonic()
    coordinator._mark_fresh("imei-1", FRESHNESS_FACETS, now)
    coordinator._mark_fresh("imei-2", FRESHNESS_FACETS, now - 1500)
    coordinator._update_polling_interval()

    due_in = coordinator.device_polling_interval("imei-2") - 1500
    assert coordinator.update_interval.total_seconds() == pytest.approx(due_in, abs=2)

    push = ZTEKidsPushManager(hass, coordinator)
    push._handle_event(
        _event("deviceNowLocation", {"imei": "imei-1", "lat": 59.91, "lon": 10.75})
    )

    # Watch 1's fix says nothing about watch 2, whose poll stays where it was.
    assert coordinator.update_interval.total_seconds() == pytest.approx(due_in, abs=2)


@pytest.mark.asyncio
async def test_a_chatty_location_stream_still_gets_polled(hass) -> None:
    """The failure mode a single shared deadline would have introduced.

    Location events must not hold polling off indefinitely: nothing pushes
    device config, step totals or unread counts, so they would silently
    freeze while the position kept looking healthy.
    """
    coordinator = _coordinator(hass)
    started = monotonic()
    coordinator._mark_fresh("imei-1", FRESHNESS_FACETS, started)

    # A fix a minute, for well past the status deadline.
    for minute in range(1, 46):
        coordinator._mark_fresh("imei-1", (FACET_LOCATION,), started + minute * 60)

    assert coordinator._should_poll_device(
        "imei-1",
        now=started + 46 * 60,
        existing_snapshot=coordinator.data.devices["imei-1"],
        force_refresh=False,
    )

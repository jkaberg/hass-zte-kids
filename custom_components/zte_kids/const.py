from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "zte_kids"
CONF_DEVICE_POLLING = "device_polling"
CONF_POLLING_ENABLED = "enabled"
CONF_POLLING_INTERVAL = "interval_seconds"
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.UPDATE,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]
DEFAULT_POLLING_INTERVAL = timedelta(minutes=30)
DEFAULT_POLLING_INTERVAL_SECONDS = 1800
DEVICE_POLLING_INTERVAL_MIN_SECONDS = 300
DEVICE_POLLING_INTERVAL_MAX_SECONDS = 3600
DEFAULT_DEVICE_POLLING_ENABLED = True

# Freshness is tracked per facet, because the two paths that deliver it cover
# different ground: a poll reads everything, while the event stream only ever
# carries a position fix or a battery level. Giving each facet its own clock
# is what stops a chatty location stream from suppressing polling altogether
# and quietly freezing the fields no event ever mentions.
FACET_LOCATION = "location"
FACET_BATTERY = "battery"
FACET_STATUS = "status"
FRESHNESS_FACETS = (FACET_LOCATION, FACET_BATTERY, FACET_STATUS)

# The status facet - device config, step totals, unread counts - is only ever
# satisfied by a poll. It tolerates being older than a position fix, so it
# gets its own, slower deadline, and is never allowed to run faster than the
# interval the user asked for.
STATUS_REFRESH_SECONDS = 1800

# Floor on how soon the next poll may be scheduled, so a deadline that is
# nearly due cannot turn a burst of events into a burst of requests.
MIN_POLL_SCHEDULE_SECONDS = 30

# Minimum spacing between commands sent to the same watch. The upstream rate
# limits are undocumented, and these commands ring, reboot or power off a
# device a child is wearing, so repeats are rejected rather than queued.
COMMAND_COOLDOWN_SECONDS = 5.0

# After asking a watch for a position fix, re-poll on this schedule (seconds
# between polls) and stop as soon as the fix timestamp moves. The watch answers
# asynchronously, so a single immediate poll would read the previous fix.
LOCATE_POLL_DELAYS_SECONDS = (8, 12, 25)

# Upper bound on an outgoing message. The wire documents no limit, so this is
# ours: long enough for any real message, short enough to fail fast on a
# template that expanded into something enormous.
MAX_MESSAGE_LENGTH = 500

# Firmware versions and safe-zone definitions change rarely, so they are read
# on this slower cadence instead of on every poll.
SLOW_REFRESH_SECONDS = 6 * 60 * 60

# Default daily step goal offered when the watch has not reported one.
DEFAULT_STEP_GOAL = 8000
STEP_GOAL_MIN = 1000
STEP_GOAL_MAX = 50000

# Real-time push is opt-in. It connects to a hard-coded third-party broker
# whose credentials are shared by every copy of the vendor app. It is on by
# default because it has been confirmed working against the live broker, and
# it can be switched off without losing anything: polling runs underneath
# regardless.
CONF_ENABLE_PUSH = "enable_push"
DEFAULT_ENABLE_PUSH = True

# How long to wait for the broker to acknowledge a connection before carrying
# on. Missing the deadline is not a failure - paho keeps retrying in the
# background - and it costs nothing either way, because a connection that has
# not delivered anything buys no reduction in polling.
PUSH_CONNECT_TIMEOUT_SECONDS = 5.0

# Bus events for push traffic that has no entity to live in.
EVENT_MESSAGE = f"{DOMAIN}_message"
EVENT_SAFE_ZONE = f"{DOMAIN}_safe_zone"

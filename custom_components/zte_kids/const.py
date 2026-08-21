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
# background - it just means polling stays at full rate until the stream is
# actually up.
PUSH_CONNECT_TIMEOUT_SECONDS = 5.0

# While the event stream is up, polling continues at this slower cadence as a
# safety net: the broker is a third-party service that can go quiet without
# telling us, and a silent stream must not look like a stationary child.
PUSH_KEEPALIVE_POLL_SECONDS = 3600

# Bus events for push traffic that has no entity to live in.
EVENT_MESSAGE = f"{DOMAIN}_message"
EVENT_SAFE_ZONE = f"{DOMAIN}_safe_zone"

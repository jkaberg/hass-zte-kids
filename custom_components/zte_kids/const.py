from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "zte_kids"
CONF_DEVICE_POLLING = "device_polling"
CONF_POLLING_ENABLED = "enabled"
CONF_POLLING_INTERVAL = "interval_seconds"
PLATFORMS: list[Platform] = [
	Platform.SENSOR,
	Platform.DEVICE_TRACKER,
	Platform.NUMBER,
	Platform.SWITCH,
	Platform.BUTTON,
]
DEFAULT_POLLING_INTERVAL = timedelta(minutes=30)
DEFAULT_POLLING_INTERVAL_SECONDS = 1800
DEVICE_POLLING_INTERVAL_MIN_SECONDS = 300
DEVICE_POLLING_INTERVAL_MAX_SECONDS = 3600
DEFAULT_DEVICE_POLLING_ENABLED = True

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_kids.const import DOMAIN
from custom_components.zte_kids.coordinator import CoordinatorData, ZTEKidsDataUpdateCoordinator
from custom_components.zte_kids.sdk.models import (
    AccountProfile,
    Credentials,
    Device,
    DeviceSnapshot,
    Session,
)
from custom_components.zte_kids.sensor import SENSORS, ZTEKidsSensor


def _mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        },
    )


def test_steps_sensor_is_numeric_total(hass) -> None:
    coordinator = ZTEKidsDataUpdateCoordinator(
        hass,
        client=MagicMock(),
        credentials=Credentials(username="user@example.com", password="secret"),
        config_entry=_mock_entry(),
    )
    data = CoordinatorData(
        session=Session(access_token="token", openid="openid"),
        profile=AccountProfile(openid="openid"),
        devices={
            "imei-1": DeviceSnapshot(
                device=Device(device_id="imei-1", name="Watch 1"),
                steps=4321,
                raw={"imei": "imei-1", "name": "Watch 1", "stepNum": "4321"},
            )
        },
    )
    coordinator.async_set_updated_data(data)
    coordinator._latest_data = data

    entity = ZTEKidsSensor(coordinator, "imei-1", SENSORS[1])

    assert entity.native_value == 4321
    assert entity.state_class == SensorStateClass.TOTAL
    assert entity._numeric_state_expected is True

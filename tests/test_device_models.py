from __future__ import annotations

from custom_components.zte_kids.sdk.models import DeviceSnapshot


def test_device_snapshot_parses_nested_battery_and_location() -> None:
    snapshot = DeviceSnapshot.from_payload(
        {
            "imei": "1234567890",
            "name": "Watch",
            "battery": {"percent": 87, "updateTime": 1710000000123},
            "lastLocation": {
                "lat": "12.3456",
                "lon": "65.4321",
                "radius": "35",
                "timestamp": 1710000000456,
                "address": "123 Example Street",
                "address_poi": "School",
                "loc_type": "gps",
            },
            "stepNum": 4321,
        }
    )

    assert snapshot.device.device_id == "1234567890"
    assert snapshot.battery == 87
    assert snapshot.battery_timestamp == 1710000000123
    assert snapshot.steps == 4321
    assert snapshot.location is not None
    assert snapshot.location.latitude == 12.3456
    assert snapshot.location.longitude == 65.4321
    assert snapshot.location.radius == 35
    assert snapshot.location.address == "123 Example Street"
    assert snapshot.location.address_poi == "School"
    assert snapshot.location.loc_type == "gps"


def test_device_snapshot_preserves_zero_values() -> None:
    snapshot = DeviceSnapshot.from_payload(
        {
            "imei": "1234567890",
            "battery": 0,
            "sportStep": 0,
            "lat": 0,
            "lon": 0,
            "radius": 0,
            "timestamp": 0,
            "type": "lbs",
        }
    )

    assert snapshot.battery == 0
    assert snapshot.steps == 0
    assert snapshot.location is not None
    assert snapshot.location.latitude == 0.0
    assert snapshot.location.longitude == 0.0
    assert snapshot.location.radius == 0
    assert snapshot.location.timestamp == 0
    assert snapshot.location.loc_type == "lbs"


def test_device_snapshot_accepts_step_aliases() -> None:
    snapshot = DeviceSnapshot.from_payload(
        {
            "imei": "1234567890",
            "step": 1234,
        }
    )

    assert snapshot.steps == 1234

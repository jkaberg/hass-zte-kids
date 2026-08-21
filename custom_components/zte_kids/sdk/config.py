from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import locale


class Environment(str, Enum):
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class MqttConfig:
    """Broker settings for the real-time event stream.

    These credentials are baked into every copy of the app and are shared by
    all of its users, so the connection is only as private as the broker's
    topic ACLs. Subscribe to this account's own topics and nothing else.
    """

    host: str
    port: int
    username: str
    password: str
    client_prefix: str
    client_id_prefix: str = "GID_LKY@@@"


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    name: Environment
    api_base_url: str
    app_key: str
    app_secret: str
    password_key: bytes
    mqtt: MqttConfig


@dataclass(frozen=True, slots=True)
class PlatformMetadata:
    package_short_name: str = "care"
    app_version: str = "2.4.7.A"
    brand: str = "nubia"
    model: str = "NX669J"
    os_name: str = "Android"
    release: str = "13"

    @classmethod
    def current(cls) -> "PlatformMetadata":
        return cls()

    @property
    def mobile_type(self) -> str:
        return f"{self.brand};{self.model};{self.os_name};{self.release}"

    @property
    def accept_language(self) -> str:
        language, _ = locale.getlocale()
        if language and language not in {"C", "POSIX"}:
            return language.split("_", 1)[0]
        return "en"

    @property
    def user_agent(self) -> str:
        return (
            f"{self.package_short_name}/{self.app_version}"
            f"({self.brand};{self.model};{self.os_name};{self.release})"
        )


ENVIRONMENTS: dict[Environment, EnvironmentConfig] = {
    Environment.PRODUCTION: EnvironmentConfig(
        name=Environment.PRODUCTION,
        api_base_url="https://care-api.nubia.com/",
        app_key="U7yJRy5eO0DKTlNVrnx4z5ICm5y16a4S",
        app_secret="fR1gX2AEiYxflz8sVsLFzfwTOfk8NzBu",
        password_key=b"YNSSFWTeip5M2hSzmpoW4dXr0rWTc0Wr",
        mqtt=MqttConfig(
            host="care.nubia.com",
            port=1883,
            username="care_android",
            password="WJJ3@PhC&EdG$eaf98Ae",
            client_prefix="watchiot",
        ),
    ),
}

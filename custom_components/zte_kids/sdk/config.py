from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import locale


class Environment(str, Enum):
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    name: Environment
    api_base_url: str
    app_key: str
    app_secret: str
    password_key: bytes


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
    ),
}

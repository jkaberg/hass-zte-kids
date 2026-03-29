"""Public SDK surface for the ZTE Kids reverse-engineered client."""

from .client import ZTEKidsClient
from .config import Environment, EnvironmentConfig, PlatformMetadata
from .exceptions import (
    APIError,
    AuthenticationError,
    CaptchaAnswerIncorrectError,
    CaptchaRefreshRequiredError,
    CaptchaRequiredError,
    SessionExpiredError,
    VerificationChallengeError,
    VerificationCodeExpiredError,
    ZTEKidsError,
)

__all__ = [
    "APIError",
    "AuthenticationError",
    "CaptchaAnswerIncorrectError",
    "CaptchaRefreshRequiredError",
    "CaptchaRequiredError",
    "Environment",
    "EnvironmentConfig",
    "PlatformMetadata",
    "SessionExpiredError",
    "VerificationChallengeError",
    "VerificationCodeExpiredError",
    "ZTEKidsClient",
    "ZTEKidsError",
]

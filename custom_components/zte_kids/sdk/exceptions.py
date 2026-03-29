from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ZTEKidsError(Exception):
    """Base SDK exception."""


@dataclass(slots=True)
class APIError(ZTEKidsError):
    code: int | None
    message: str
    payload: Any | None = None

    def __str__(self) -> str:
        if self.code is None:
            return self.message
        return f"API error {self.code}: {self.message}"


class AuthenticationError(ZTEKidsError):
    """Raised when credentials or token material are invalid."""


@dataclass(slots=True)
class VerificationChallengeError(APIError):
    """Raised when the upstream requires or rejects an interactive challenge."""


@dataclass(slots=True)
class CaptchaAnswerIncorrectError(VerificationChallengeError):
    """Raised when a supplied captcha or challenge answer is rejected."""


@dataclass(slots=True)
class CaptchaRefreshRequiredError(VerificationChallengeError):
    """Raised when the upstream invalidates the current challenge and requires a new one."""


@dataclass(slots=True)
class VerificationCodeExpiredError(VerificationChallengeError):
    """Raised when an upstream verification code or challenge has expired."""


@dataclass(slots=True)
class CaptchaRequiredError(AuthenticationError):
    message: str = "Interactive captcha verification is required."
    challenge: Any | None = None
    payload: Any | None = None

    def __str__(self) -> str:
        return self.message


class SessionExpiredError(APIError):
    """Raised when the upstream API indicates a forced logout."""

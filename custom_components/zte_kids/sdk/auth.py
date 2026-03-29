from __future__ import annotations

from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
import time
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import EnvironmentConfig


def build_nonce() -> str:
    return uuid.uuid4().hex


def build_timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def _java_value_to_string(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class SigningMaterial:
    sign: str
    timestamp: str
    nonce: str
    app_key: str

    @property
    def query_params(self) -> dict[str, str]:
        return {
            "sign": self.sign,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "appKey": self.app_key,
        }


def build_signature(
    *,
    config: EnvironmentConfig,
    method: str,
    query_params: Mapping[str, object] | None = None,
    json_body: Mapping[str, object] | None = None,
    form_fields: Mapping[str, object] | None = None,
    multipart_text_fields: Mapping[str, object] | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> SigningMaterial:
    material_timestamp = timestamp or build_timestamp_ms()
    material_nonce = nonce or build_nonce()

    sign_items: dict[str, object] = {
        "timestamp": material_timestamp,
        "nonce": material_nonce,
        "appKey": config.app_key,
    }

    upper_method = method.upper()
    if upper_method in {"GET", "DELETE"} and query_params is not None:
        sign_items.update(query_params)
    elif upper_method == "POST":
        if form_fields is not None:
            sign_items.update(form_fields)
        elif multipart_text_fields is not None:
            sign_items.update(multipart_text_fields)
        elif json_body is not None:
            sign_items.update(json_body)

    ordered_items = sorted(sign_items.items(), key=lambda item: item[0])
    signing_string = "".join(
        f"{key}={_java_value_to_string(value)}&" for key, value in ordered_items
    ) + config.app_secret
    signature = hashlib.sha256(signing_string.encode("utf-8")).hexdigest()
    return SigningMaterial(
        sign=signature,
        timestamp=material_timestamp,
        nonce=material_nonce,
        app_key=config.app_key,
    )


class PasswordCodec:
    """Replicates the app's AES/GCM/NoPadding password transformation."""

    def __init__(self, config: EnvironmentConfig) -> None:
        self._aesgcm = AESGCM(config.password_key)

    def encrypt(self, password: str, *, nonce: bytes | None = None) -> str:
        iv = nonce or os.urandom(12)
        ciphertext = self._aesgcm.encrypt(iv, password.encode("utf-8"), None)
        return b64encode(iv + ciphertext).decode("utf-8")

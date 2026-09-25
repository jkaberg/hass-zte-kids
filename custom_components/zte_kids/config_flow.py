from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.httpx_client import get_async_client
import voluptuous as vol

from .const import CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH, DOMAIN
from .sdk import Environment, ZTEKidsClient
from .sdk.exceptions import CaptchaRequiredError, ZTEKidsError
from .sdk.models import Credentials


class ZTEKidsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ZTEKidsOptionsFlow:
        return ZTEKidsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self._async_step_configure(user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await self._validate_input(
                    {
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                )
            except CaptchaRequiredError:
                errors["base"] = "captcha_required"
            except ZTEKidsError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(entry.data[CONF_USERNAME].lower())
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_step_configure(user_input, reconfigure=True)

    async def _async_step_configure(
        self,
        user_input: dict[str, Any] | None,
        *,
        reconfigure: bool = False,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            normalized_input = {
                **user_input,
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
            }
            try:
                await self._validate_input(normalized_input)
            except CaptchaRequiredError:
                errors["base"] = "captcha_required"
            except ZTEKidsError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(normalized_input[CONF_USERNAME].lower())
                if reconfigure:
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        data_updates=normalized_input,
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=normalized_input[CONF_USERNAME],
                    data=normalized_input,
                )

        return self.async_show_form(
            step_id="reconfigure" if reconfigure else "user",
            data_schema=self._build_schema(reconfigure=reconfigure),
            errors=errors,
        )

    def _build_schema(self, *, reconfigure: bool) -> vol.Schema:
        defaults = self._get_reconfigure_entry().data if reconfigure else {}

        return vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            }
        )

    async def _validate_input(self, user_input: dict[str, Any]) -> None:
        client = ZTEKidsClient(
            environment=Environment.PRODUCTION,
            http_client=get_async_client(self.hass),
            close_http_client=False,
        )
        try:
            await client.auth.login(
                Credentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
            )
        finally:
            await client.aclose()


class ZTEKidsOptionsFlow(config_entries.OptionsFlow):
    """Settings that change how the integration talks to the service."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        current = self.config_entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_ENABLE_PUSH, default=current): bool}
            ),
        )

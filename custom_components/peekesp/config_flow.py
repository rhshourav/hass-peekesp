"""Config flow: pair with a code, make one, or enter a URL and token.

Setup menu:   pair | generate | manual | links
Options menu: settings | pairing_code (paired entries only) | links

Every one of those has an action that does the same thing without the dialog
(see services.py), and the two that create an entry also have an import step
below, which is how those actions reach this file.
"""
from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    ATTR_STORE_CODE,
    CONF_CODE,
    CONF_MODE,
    CONF_OFFLINE_AFTER,
    CONF_REGENERATE,
    CONF_RELAY_BASE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_OFFLINE_AFTER,
    DEFAULT_RELAY_BASE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LINKS,
    MAX_OFFLINE_AFTER,
    MAX_SCAN_INTERVAL,
    MIN_OFFLINE_AFTER,
    MIN_SCAN_INTERVAL,
    MODE_MANUAL,
    MODE_PAIRED,
)
from .entries import async_probe, paired_update, relay_base
from .pairing import derive, format_code, is_valid_code, new_code, normalize_code

PAIR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CODE): str,
        vol.Required(CONF_RELAY_BASE, default=DEFAULT_RELAY_BASE): str,
    }
)
MANUAL_SCHEMA = vol.Schema({vol.Required(CONF_URL): str, vol.Required(CONF_TOKEN): str})
GENERATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RELAY_BASE, default=DEFAULT_RELAY_BASE): str,
        vol.Optional(CONF_REGENERATE, default=False): bool,
    }
)
ROTATE_SCHEMA = vol.Schema({vol.Optional(CONF_REGENERATE, default=False): bool})


class PeekConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # Held for the life of the flow so the code on screen does not change
        # under someone who is halfway through copying it.
        self._generated_code: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["pair", "generate", "manual", "links"]
        )

    # --- links: GitHub, the repositories, Discord ------------------------------
    async def async_step_links(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A menu with one way out, so it can carry text and links and still go back."""
        return self.async_show_menu(
            step_id="links", menu_options=["user"], description_placeholders=dict(LINKS)
        )

    # --- generate: make a code here and listen on it ---------------------------
    async def async_step_generate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Make a pairing code, show it, and listen on it.

        The display invents its own code, so a Home Assistant user with no
        display (or one who wants to start from the agents) had no code to
        start from. The relay never sees a code, so there is nothing to
        register: the stream exists once something pushes to it.
        """
        if self._generated_code is None:
            self._generated_code = new_code()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_REGENERATE):
                self._generated_code = new_code()
                user_input = {**user_input, CONF_REGENERATE: False}
            else:
                base = user_input[CONF_RELAY_BASE].strip().rstrip("/")
                result, errors = await self._pair(self._generated_code, base, store_code=True)
                if result is not None:
                    return result
        return self.async_show_form(
            step_id="generate",
            data_schema=self.add_suggested_values_to_schema(GENERATE_SCHEMA, user_input),
            description_placeholders={"code": format_code(self._generated_code)},
            errors=errors,
        )

    # --- paired: the code shown on the device's screen -------------------------
    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._pair(
                normalize_code(user_input[CONF_CODE]),
                user_input[CONF_RELAY_BASE].strip().rstrip("/"),
                # Least privilege: the code can push and command, the read token
                # cannot, so a code somebody typed in is not kept.
                store_code=False,
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="pair",
            data_schema=self.add_suggested_values_to_schema(PAIR_SCHEMA, user_input),
            errors=errors,
        )

    # --- manual: a named or private stream -------------------------------------
    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._manual(
                user_input[CONF_URL].strip(), user_input[CONF_TOKEN].strip()
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, user_input),
            errors=errors,
        )

    # --- import: the peekesp.pair / peekesp.add_custom_relay actions ------------
    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """No form to show, so a problem ends the flow with a reason instead."""
        if CONF_CODE in import_data:
            result, errors = await self._pair(
                normalize_code(import_data[CONF_CODE]),
                import_data.get(CONF_RELAY_BASE, DEFAULT_RELAY_BASE).strip().rstrip("/"),
                store_code=bool(import_data.get(ATTR_STORE_CODE)),
            )
        else:
            result, errors = await self._manual(
                import_data[CONF_URL].strip(), import_data[CONF_TOKEN].strip()
            )
        if result is not None:
            return result
        return self.async_abort(reason=next(iter(errors.values())))

    # --- reauth: the relay stopped accepting our token --------------------------
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        paired = entry.data.get(CONF_MODE) == MODE_PAIRED
        if user_input is not None:
            updates: dict[str, Any] = {}
            if paired:
                code = normalize_code(user_input[CONF_CODE])
                if not is_valid_code(code):
                    errors[CONF_CODE] = "invalid_code"
                else:
                    # A code someone typed in is not stored, and a stored code
                    # that no longer applies must not linger and be shown.
                    updates = paired_update(entry, code, keep_code=False)
            else:
                token = user_input[CONF_TOKEN].strip()
                updates = {"data": {**entry.data, CONF_TOKEN: token}}
            if not errors:
                if error := await async_probe(
                    self.hass, updates["data"][CONF_URL], updates["data"][CONF_TOKEN]
                ):
                    errors["base"] = error
                else:
                    other = (
                        self.hass.config_entries.async_entry_for_domain_unique_id(
                            DOMAIN, updates["unique_id"]
                        )
                        if "unique_id" in updates
                        else None
                    )
                    if other is not None and other.entry_id != entry.entry_id:
                        return self.async_abort(reason="already_configured")
                    return self.async_update_reload_and_abort(entry, **updates)
        schema = vol.Schema({vol.Required(CONF_CODE if paired else CONF_TOKEN): str})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    # --- shared by the forms above and the import step --------------------------
    async def _pair(
        self, code: str, base: str, *, store_code: bool
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        """Check a code and a relay, and make the entry. (result, {}) or (None, errors)."""
        if not is_valid_code(code):
            return None, {CONF_CODE: "invalid_code"}
        if not base.startswith("https://"):
            return None, {CONF_RELAY_BASE: "invalid_url"}
        stream, token = derive(code)
        url = f"{base}/telemetry/{stream}"
        if error := await async_probe(self.hass, url, token):
            return None, {"base": error}
        await self.async_set_unique_id(stream)
        self._abort_if_unique_id_configured()
        data = {CONF_MODE: MODE_PAIRED, CONF_URL: url, CONF_TOKEN: token}
        if store_code:
            data[CONF_CODE] = code
        return self.async_create_entry(title=f"PeekESP {stream[:6]}", data=data), {}

    async def _manual(
        self, url: str, token: str
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        if not url.startswith("https://"):
            return None, {CONF_URL: "invalid_url"}
        if error := await async_probe(self.hass, url, token):
            return None, {"base": error}
        await self.async_set_unique_id(hashlib.sha256(url.encode()).hexdigest()[:16])
        self._abort_if_unique_id_configured()
        return (
            self.async_create_entry(
                title="PeekESP (custom relay)",
                data={CONF_MODE: MODE_MANUAL, CONF_URL: url, CONF_TOKEN: token},
            ),
            {},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return PeekOptionsFlow()


class PeekOptionsFlow(OptionsFlow):
    """Configure: settings, the pairing code, and where to find the project."""

    def __init__(self) -> None:
        self._new_code: str | None = None

    @property
    def _paired(self) -> bool:
        return self.config_entry.data.get(CONF_MODE) == MODE_PAIRED

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # A custom relay has no pairing code, so there is nothing to show or change.
        options = ["settings", "pairing_code", "links"] if self._paired else ["settings", "links"]
        return self.async_show_menu(step_id="init", menu_options=options)

    # --- settings ---------------------------------------------------------------
    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                vol.Required(
                    CONF_OFFLINE_AFTER, default=o.get(CONF_OFFLINE_AFTER, DEFAULT_OFFLINE_AFTER)
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_OFFLINE_AFTER, max=MAX_OFFLINE_AFTER)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # --- links ------------------------------------------------------------------
    async def async_step_links(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="links", menu_options=["init"], description_placeholders=dict(LINKS)
        )

    # --- the pairing code -------------------------------------------------------
    async def async_step_pairing_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the code, and the URL and token the ESP32's setup page asks for.

        The code is only there if Home Assistant made it. One a person typed in
        was never kept (a read token cannot be turned back into a code), and
        saying so beats showing something blank.
        """
        data = self.config_entry.data
        placeholders = {"worker_url": data[CONF_URL], "read_token": data[CONF_TOKEN]}
        code = data.get(CONF_CODE)
        if not code:
            return self.async_show_menu(
                step_id="pairing_unknown",
                menu_options=["rotate_code", "init"],
                description_placeholders=placeholders,
            )
        return self.async_show_menu(
            step_id="pairing_code",
            menu_options=["rotate_code", "init"],
            description_placeholders={"code": format_code(code), **placeholders},
        )

    async def async_step_pairing_unknown(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_pairing_code()

    async def async_step_rotate_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace this entry's code with a new one.

        Every agent, the app and the display that use the old code stop
        reaching this stream, so the dialog says so before it does anything,
        and nothing changes until the person submits.
        """
        if self._new_code is None:
            self._new_code = new_code()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_REGENERATE):
                self._new_code = new_code()
            else:
                stream, token = derive(self._new_code)
                url = f"{relay_base(self.config_entry.data[CONF_URL])}/telemetry/{stream}"
                if error := await async_probe(self.hass, url, token):
                    errors["base"] = error
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        **paired_update(self.config_entry, self._new_code, keep_code=True),
                    )
                    # The options themselves are unchanged; this just ends the flow.
                    return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="rotate_code",
            data_schema=ROTATE_SCHEMA,
            description_placeholders={"code": format_code(self._new_code)},
            errors=errors,
        )

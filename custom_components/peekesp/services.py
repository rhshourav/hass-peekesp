"""Actions: everything the setup and options dialogs can do, callable from automations.

Registered once for the integration (in async_setup), not once per config
entry, so they survive an entry being reloaded or removed. Home Assistant only
runs async_setup for an integration that has an entry or a YAML key, so before
the first entry they exist only if configuration.yaml has an empty `peekesp:`.

    dialog entry                   action
    -----------------------------  ---------------------------------------------
    setup   > pairing code         peekesp.pair                  (administrators)
    setup   > generate a code      peekesp.generate_pairing_code (response)
    setup   > URL and token        peekesp.add_custom_relay      (administrators)
    either  > links                peekesp.get_links             (response)
    options > settings             peekesp.set_options           (administrators)
    options > pairing code         peekesp.get_pairing_code      (administrators)
    options > make a new code      peekesp.rotate_pairing_code   (administrators)
    (button) refresh now           peekesp.refresh

Anything that creates or changes an entry, or hands back a credential, is for
administrators only, as in the dialogs. Without a user (an automation, a
script) the call is trusted, as for every other administrator action.
"""
from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_NOTIFY,
    ATTR_STORE_CODE,
    CONF_CODE,
    CONF_MODE,
    CONF_OFFLINE_AFTER,
    CONF_RELAY_BASE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_RELAY_BASE,
    DOMAIN,
    LINKS,
    MAX_OFFLINE_AFTER,
    MAX_SCAN_INTERVAL,
    MIN_OFFLINE_AFTER,
    MIN_SCAN_INTERVAL,
    MODE_PAIRED,
    SERVICE_ADD_CUSTOM_RELAY,
    SERVICE_GENERATE_PAIRING_CODE,
    SERVICE_GET_LINKS,
    SERVICE_GET_PAIRING_CODE,
    SERVICE_PAIR,
    SERVICE_REFRESH,
    SERVICE_ROTATE_PAIRING_CODE,
    SERVICE_SET_OPTIONS,
)
from .entries import async_probe, paired_update, relay_base
from .pairing import derive, format_code, new_code

_ENTRY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})
_LINKS_SCHEMA = vol.Schema({vol.Optional(ATTR_NOTIFY, default=False): cv.boolean})
_SET_OPTIONS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Optional(CONF_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
            ),
            vol.Optional(CONF_OFFLINE_AFTER): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_OFFLINE_AFTER, max=MAX_OFFLINE_AFTER)
            ),
        }
    ),
    cv.has_at_least_one_key(CONF_SCAN_INTERVAL, CONF_OFFLINE_AFTER),
)
_PAIR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CODE): cv.string,
        vol.Optional(CONF_RELAY_BASE, default=DEFAULT_RELAY_BASE): cv.string,
        vol.Optional(ATTR_STORE_CODE, default=False): cv.boolean,
    }
)
_ADD_CUSTOM_RELAY_SCHEMA = vol.Schema(
    {vol.Required(CONF_URL): cv.string, vol.Required(CONF_TOKEN): cv.string}
)

NOTIFICATION_ID = f"{DOMAIN}_links"

# What the import step can end a flow with, split by whose fault it is.
_BAD_INPUT = {"invalid_code", "invalid_url", "already_configured"}
_RELAY_TROUBLE = {"invalid_auth", "cannot_connect"}


def links_markdown() -> str:
    return (
        f"- [rhshourav on GitHub]({LINKS['github_profile']})\n"
        f"- [PeekESP repository]({LINKS['repo_main']}) (firmware, agents, relay, app)\n"
        f"- [Home Assistant integration repository]({LINKS['repo_ha']})\n"
        f"- [Join the PeekESP Discord]({LINKS['discord']})"
    )


@callback
def async_post_links(hass: HomeAssistant) -> None:
    """Put the links in a notification. Home Assistant cannot open a browser tab
    for you from a server-side action; a notification is the closest thing that
    is still clickable, and it works from a button, a script or an automation."""
    persistent_notification.async_create(
        hass, links_markdown(), title="PeekESP links", notification_id=NOTIFICATION_ID
    )


def _entries(hass: HomeAssistant, call: ServiceCall, *, loaded_only: bool) -> list[ConfigEntry]:
    """The entries an action applies to: the one named, or all of them."""
    entries = hass.config_entries.async_entries(DOMAIN)
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_entry",
                translation_placeholders={"entry_id": wanted},
            )
    if loaded_only:
        for e in entries:
            if e.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                    translation_placeholders={"title": e.title},
                )
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entries")
    return entries


def _one_entry(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    """For an action that reads or changes one entry's credential: never guess which."""
    entries = _entries(hass, call, loaded_only=False)
    if len(entries) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="multiple_entries")
    return entries[0]


async def _add_entry(hass: HomeAssistant, data: dict) -> ServiceResponse:
    """Create an entry through the import step, so it is checked like the dialog's."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    if result["type"] is FlowResultType.CREATE_ENTRY:
        entry = result["result"]
        return {"config_entry_id": entry.entry_id, "title": entry.title}
    reason = result.get("reason")
    if reason in _BAD_INPUT:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=reason)
    if reason in _RELAY_TROUBLE:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key=reason)
    raise HomeAssistantError(f"PeekESP setup stopped: {reason or result['type']}")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    # --- pairing codes ------------------------------------------------------
    async def generate_pairing_code(call: ServiceCall) -> ServiceResponse:
        code = new_code()
        stream, _read_token = derive(code)
        return {"code": code, "code_formatted": format_code(code), "stream_id": stream}

    async def get_pairing_code(call: ServiceCall) -> ServiceResponse:
        entry = _one_entry(hass, call)
        code = entry.data.get(CONF_CODE)
        if not code:
            # Entered by hand, or a custom relay: only a derived read token was
            # kept, and that cannot be turned back into the code.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_code_stored",
                translation_placeholders={"title": entry.title},
            )
        return {
            "config_entry_id": entry.entry_id,
            "title": entry.title,
            "code": code,
            "code_formatted": format_code(code),
        }

    async def rotate_pairing_code(call: ServiceCall) -> ServiceResponse:
        """The options dialog's "make a new code", minus the confirmation page.

        Agents, the app and the display using the old code stop reaching this
        stream until they are given the new one, exactly as in the dialog.
        """
        entry = _one_entry(hass, call)
        if entry.data.get(CONF_MODE) != MODE_PAIRED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_paired",
                translation_placeholders={"title": entry.title},
            )
        code = new_code()
        stream, token = derive(code)
        url = f"{relay_base(entry.data[CONF_URL])}/telemetry/{stream}"
        if error := await async_probe(hass, url, token):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key=error)
        hass.config_entries.async_update_entry(entry, **paired_update(entry, code, keep_code=True))
        return {
            "config_entry_id": entry.entry_id,
            "title": entry.title,
            "code": code,
            "code_formatted": format_code(code),
            "stream_id": stream,
        }

    # --- adding an entry ----------------------------------------------------
    async def pair(call: ServiceCall) -> ServiceResponse:
        return await _add_entry(
            hass,
            {
                CONF_CODE: call.data[CONF_CODE],
                CONF_RELAY_BASE: call.data[CONF_RELAY_BASE],
                ATTR_STORE_CODE: call.data[ATTR_STORE_CODE],
            },
        )

    async def add_custom_relay(call: ServiceCall) -> ServiceResponse:
        return await _add_entry(
            hass, {CONF_URL: call.data[CONF_URL], CONF_TOKEN: call.data[CONF_TOKEN]}
        )

    # --- settings, links, refresh ---------------------------------------------
    async def set_options(call: ServiceCall) -> None:
        changes = {
            k: call.data[k] for k in (CONF_SCAN_INTERVAL, CONF_OFFLINE_AFTER) if k in call.data
        }
        for entry in _entries(hass, call, loaded_only=False):
            # Reloads the entry, as saving the options dialog does.
            hass.config_entries.async_update_entry(entry, options={**entry.options, **changes})

    async def get_links(call: ServiceCall) -> ServiceResponse:
        if call.data[ATTR_NOTIFY]:
            async_post_links(hass)
        return dict(LINKS)

    async def refresh(call: ServiceCall) -> None:
        entries = _entries(hass, call, loaded_only=True)
        await asyncio.gather(*(e.runtime_data.async_request_refresh() for e in entries))

    # Open to every user: nothing here is a credential or changes anything.
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_PAIRING_CODE,
        generate_pairing_code,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LINKS,
        get_links,
        schema=_LINKS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=_ENTRY_SCHEMA)

    # Administrators only: a response is a credential (a script's trace would
    # otherwise hand it to anyone who can see that script run), and the rest
    # create or change an entry, as the dialogs do.
    for name, handler, schema, response in (
        (SERVICE_GET_PAIRING_CODE, get_pairing_code, _ENTRY_SCHEMA, SupportsResponse.ONLY),
        (SERVICE_ROTATE_PAIRING_CODE, rotate_pairing_code, _ENTRY_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_SET_OPTIONS, set_options, _SET_OPTIONS_SCHEMA, SupportsResponse.NONE),
        (SERVICE_PAIR, pair, _PAIR_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_ADD_CUSTOM_RELAY, add_custom_relay, _ADD_CUSTOM_RELAY_SCHEMA, SupportsResponse.OPTIONAL),
    ):
        async_register_admin_service(
            hass, DOMAIN, name, handler, schema=schema, supports_response=response
        )

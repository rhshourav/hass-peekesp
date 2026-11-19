"""PeekESP: your PeekESP machines, and the device's own screen, in Home Assistant."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import PeekRelayClient
from .const import CARD_URL, CONF_TOKEN, CONF_URL, DOMAIN, URL_REPO_MAIN
from .coordinator import PeekCoordinator
from .services import async_setup_services

PLATFORMS = ["sensor", "binary_sensor", "button"]
_FRONTEND_KEY = f"{DOMAIN}_frontend"

# Entries are made in the UI, not in YAML. An empty `peekesp:` line is accepted
# without complaint on purpose: it is what loads the integration (and so its
# actions) before the first entry exists, which is the only way peekesp.pair can
# be the thing that makes the first entry.
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Actions are registered here, once, rather than per config entry."""
    async_setup_services(hass)
    return True


async def _register_card(hass: HomeAssistant) -> None:
    """Serve the Lovelace card and load it on every dashboard, once."""
    if hass.data.get(_FRONTEND_KEY):
        return
    hass.data[_FRONTEND_KEY] = True
    path = Path(__file__).parent / "frontend" / "peekesp-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    # Cache-bust on file change rather than on a version nobody remembers to bump.
    # stat() is file I/O, so it runs in the executor, not on the event loop.
    mtime = (await hass.async_add_executor_job(path.stat)).st_mtime
    add_extra_js_url(hass, f"{CARD_URL}?m={int(mtime)}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _register_card(hass)

    client = PeekRelayClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN]
    )
    coordinator = PeekCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # The relay is the parent device; machines hang off it via_device.
    # configuration_url is what puts a "Visit" button on the device page.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="PeekESP relay",
        manufacturer="PeekESP",
        model="Cloudflare relay",
        configuration_url=URL_REPO_MAIN,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

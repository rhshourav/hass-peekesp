"""What the setup dialog, the options dialog and the actions all need to do.

Kept in one place so a dialog and the action that mirrors it cannot drift apart.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PeekAuthError, PeekConnectionError, PeekRelayClient
from .const import CONF_CODE, CONF_TOKEN, CONF_URL
from .pairing import derive


def relay_base(url: str) -> str:
    """'https://relay/telemetry/abc' -> 'https://relay'."""
    return url.split("/telemetry/")[0]


async def async_probe(hass: HomeAssistant, url: str, token: str) -> str | None:
    """Ask the relay once. None means it answered; otherwise the error key.

    The relay cannot tell a mistyped code from a new code nothing has pushed to
    yet (both read as an empty stream), so a freshly generated code passes.
    """
    client = PeekRelayClient(async_get_clientsession(hass), url, token)
    try:
        await client.fetch()
    except PeekAuthError:
        return "invalid_auth"
    except PeekConnectionError:
        return "cannot_connect"
    return None


def paired_update(entry: ConfigEntry, code: str, *, keep_code: bool) -> dict[str, Any]:
    """Keyword arguments for async_update_entry that move a paired entry to `code`.

    The relay address is kept, the stream, token and unique id follow the code,
    and so does the title, but only while it is still the automatic one: a name
    somebody typed in is theirs. `keep_code` is True when Home Assistant made
    the code (so it can be shown again) and False when a person typed it in.
    """
    stream, token = derive(code)
    data = {k: v for k, v in entry.data.items() if k != CONF_CODE}
    data[CONF_URL] = f"{relay_base(entry.data[CONF_URL])}/telemetry/{stream}"
    data[CONF_TOKEN] = token
    if keep_code:
        data[CONF_CODE] = code
    automatic = f"PeekESP {entry.unique_id[:6]}" if entry.unique_id else None
    title = f"PeekESP {stream[:6]}" if automatic and entry.title == automatic else entry.title
    return {"data": data, "unique_id": stream, "title": title}

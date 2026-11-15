"""One poll of the relay, shared by every entity."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PeekAuthError, PeekConnectionError, PeekRelayClient, RelayData
from .const import (
    CONF_OFFLINE_AFTER,
    CONF_SCAN_INTERVAL,
    DEFAULT_OFFLINE_AFTER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

EMPTY_WARN_AFTER = 300  # seconds


class PeekCoordinator(DataUpdateCoordinator[RelayData]):
    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: PeekRelayClient
    ) -> None:
        interval = max(
            MIN_SCAN_INTERVAL, int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self._client = client
        self._empty_since: float | None = None  # monotonic time the relay first came back with no machines
        self._warned_empty = False

    @property
    def offline_after(self) -> int:
        return int(self.config_entry.options.get(CONF_OFFLINE_AFTER, DEFAULT_OFFLINE_AFTER))

    async def _async_update_data(self) -> RelayData:
        try:
            data = await self._client.fetch()
            self._note_machines(data)
            return data
        except PeekAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PeekConnectionError as err:
            raise UpdateFailed(f"Cannot reach the relay: {err}") from err

    def _note_machines(self, data: RelayData) -> None:
        """Say so, once, when the relay answers but nothing is reporting.

        A relay that is up and empty is a valid state (nothing has pushed yet),
        so it is not an error - but it looks exactly like a working setup, and
        the usual cause is a relay that is not the one the agent pushes to.
        """
        if data.machines:
            self._empty_since = None
            self._warned_empty = False
            return
        now = time.monotonic()
        if self._empty_since is None:
            self._empty_since = now
        elif not self._warned_empty and now - self._empty_since >= EMPTY_WARN_AFTER:
            self._warned_empty = True
            _LOGGER.warning(
                "Relay %s is reachable but has reported no machines for %d minutes. "
                "Either nothing is pushing to it, or the agent/device uses a different "
                "relay than this entry; if the entry predates a relay change, delete it "
                "and add it again.",
                self._client.host,
                EMPTY_WARN_AFTER // 60,
            )

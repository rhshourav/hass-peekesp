"""Buttons: poll now, and show the project links."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PeekCoordinator
from .services import async_post_links


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PeekCoordinator = entry.runtime_data
    async_add_entities([PeekRefreshButton(coordinator), PeekLinksButton(coordinator)])


class _PeekRelayButton(ButtonEntity):
    """Not a CoordinatorEntity on purpose.

    A coordinator entity goes unavailable when the last poll failed, which is
    precisely when someone wants to press "refresh". These stay pressable.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: PeekCoordinator, key: str) -> None:
        self._coordinator = coordinator
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_relay_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})


class PeekRefreshButton(_PeekRelayButton):
    _attr_name = "Refresh now"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: PeekCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        # Debounced by the coordinator (10 s cooldown), so holding the button
        # down cannot hammer a relay that is one shared free instance.
        await self._coordinator.async_request_refresh()


class PeekLinksButton(_PeekRelayButton):
    _attr_name = "Show links"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PeekCoordinator) -> None:
        super().__init__(coordinator, "links")

    async def async_press(self) -> None:
        async_post_links(self.hass)

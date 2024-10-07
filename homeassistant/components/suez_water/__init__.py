"""The Suez Water integration."""

from __future__ import annotations

import logging

from pysuez import SuezClient, SuezData
from pysuez.async_client import SuezAsyncClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_COUNTER_ID, DOMAIN
from .coordinator import SuezWaterCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Suez Water from a config entry."""

    async_client = SuezAsyncClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_COUNTER_ID],
    )
    data = SuezData(async_client)
    coordinator = SuezWaterCoordinator(
        hass, async_client, data, entry.data[CONF_COUNTER_ID]
    )
    await coordinator.async_config_entry_first_refresh()
    client = SuezClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_COUNTER_ID],
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

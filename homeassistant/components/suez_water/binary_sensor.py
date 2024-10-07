"""Sensor for Suez Water Consumption data."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COUNTER_ID, DOMAIN
from .coordinator import SuezWaterCoordinator

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=12)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Suez Water binary sensor from a config entry."""
    dic = hass.data[DOMAIN][entry.entry_id]
    coordinator: SuezWaterCoordinator = dic["coordinator"]
    counter_id = entry.data[CONF_COUNTER_ID]
    async_add_entities(
        [
            SuezLeakAlertSensor(coordinator, counter_id),
            SuezOverConsumptionAlertSensor(coordinator, counter_id),
        ],
    )


class _SuezBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Suez Binary Sensor."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SuezWaterCoordinator, counter_id: int, name: str
    ) -> None:
        """Initialize the data object."""
        super().__init__(coordinator, context=counter_id)
        self.coordinator: SuezWaterCoordinator = coordinator
        self._attr_extra_state_attributes = {}
        self._attr_translation_key = name
        self._attr_unique_id = f"{counter_id}_{name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(counter_id))},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Suez",
        )
        self._attr_attribution = self.coordinator.get_attribution()

    async def async_update(self) -> None:
        """Update Suez binary sensor."""
        await self.coordinator.async_request_refresh()


class _SuezAlertBinarySensor(_SuezBinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM


class SuezLeakAlertSensor(_SuezAlertBinarySensor):
    """Representation of a Leak Binary Sensor."""

    def __init__(self, coordinator: SuezWaterCoordinator, counter_id: int) -> None:
        """Initialize suez leak alert sensor."""
        super().__init__(coordinator, counter_id, "leak_sensor")

    @property
    def is_on(self) -> bool | None:
        """Return the current daily usage."""
        if self.coordinator.alerts is None:
            return None
        leak: bool = self.coordinator.alerts.leak
        return leak


class SuezOverConsumptionAlertSensor(_SuezAlertBinarySensor):
    """Representation of an overconsumption binary Sensor."""

    def __init__(self, coordinator: SuezWaterCoordinator, counter_id: int) -> None:
        """Initialize suez overconsumption alert sensor."""
        super().__init__(coordinator, counter_id, "overconsumption_sensor")

    @property
    def is_on(self) -> bool | None:
        """Return the current daily usage."""
        if self.coordinator.alerts is None:
            return None
        overconsumption: bool = self.coordinator.alerts.overconsumption
        return overconsumption

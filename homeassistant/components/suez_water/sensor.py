"""Sensor for Suez Water Consumption data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
import logging
from typing import Any

from pysuez import SuezClient
from pysuez.client import PySuezError

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COUNTER_ID, DOMAIN
from .coordinator import SuezWaterCoordinator

SCAN_INTERVAL = timedelta(minutes=5)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Suez Water sensor from a config entry."""
    dic = hass.data[DOMAIN][entry.entry_id]
    coordinator = dic["coordinator"]
    client = dic["client"]
    counter_id = entry.data[CONF_COUNTER_ID]
    async_add_entities(
        [
            SuezLastDayConsumptionSensor(coordinator, counter_id),
            SuezForeverTotalIncreasingSensor(coordinator, counter_id),
            SuezPriceSensor(coordinator, counter_id),
        ],
    )
    async_add_entities(
        [
            SuezAggregatedSensor(client, counter_id),
        ],
        True,
    )


class SuezSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a Suez Sensor."""

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
        """Update Suez sensor."""
        await self.coordinator.async_request_refresh()


class SuezLastDayConsumptionSensor(SuezSensorEntity):
    """Representation of Suez yesterday Sensor."""

    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_device_class = SensorDeviceClass.WATER

    def __init__(self, coordinator: SuezWaterCoordinator, counter_id: int) -> None:
        """Initialize the data object."""
        super().__init__(coordinator, counter_id, "water_usage_last_day")

    @property
    def native_value(self) -> float | None:
        """Return the current daily usage."""
        if self.coordinator.consumption_last_day is None:
            return None
        consumption: float = self.coordinator.consumption_last_day.day_consumption
        return consumption

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return last day consumption attributes."""
        if self.coordinator.consumption_last_day is None:
            return None
        return {
            "date": self.coordinator.consumption_last_day.date
        }


class SuezPriceSensor(SuezSensorEntity):
    """Representation of a Price Sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_EURO + "/" + UnitOfVolume.CUBIC_METERS

    def __init__(self, coordinator: SuezWaterCoordinator, counter_id: int) -> None:
        """Initialize Price sensor."""
        super().__init__(coordinator, counter_id, "price_sensor")

    @property
    def native_value(self) -> float | None:
        """Return the current water price."""
        return self.coordinator.price


class SuezForeverTotalIncreasingSensor(SuezSensorEntity):
    """Representation of a Suez Forever Total Increasing Sensor."""

    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: SuezWaterCoordinator, counter_id: int) -> None:
        """Initialize suez forever total increasing."""
        super().__init__(coordinator, counter_id, "water_usage_forever_total")

    @property
    def native_value(self) -> float | None:
        """Return the current total usage."""
        if self.coordinator.index is None:
            return None
        index: float = self.coordinator.index.content.index
        return index


class SuezAggregatedSensor(SensorEntity):
    """Representation of a Suez water Sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "water_usage_yesterday"
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_device_class = SensorDeviceClass.WATER

    def __init__(self, client: SuezClient, counter_id: int) -> None:
        """Initialize the data object."""
        self.client = client
        self._attr_extra_state_attributes = {}
        self._attr_unique_id = f"{counter_id}_water_usage_yesterday"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(counter_id))},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Suez",
        )

    def _fetch_data(self) -> None:
        """Fetch latest data from Suez."""
        try:
            self.client.update()
            # _state holds the volume of consumed water during previous day
            self._attr_native_value = self.client.state
            self._attr_available = True
            self._attr_attribution = self.client.attributes["attribution"]

            self._attr_extra_state_attributes["this_month_consumption"] = {}
            for item in self.client.attributes["thisMonthConsumption"]:
                self._attr_extra_state_attributes["this_month_consumption"][item] = (
                    self.client.attributes["thisMonthConsumption"][item]
                )
            self._attr_extra_state_attributes["previous_month_consumption"] = {}
            for item in self.client.attributes["previousMonthConsumption"]:
                self._attr_extra_state_attributes["previous_month_consumption"][
                    item
                ] = self.client.attributes["previousMonthConsumption"][item]
            self._attr_extra_state_attributes["highest_monthly_consumption"] = (
                self.client.attributes["highestMonthlyConsumption"]
            )
            self._attr_extra_state_attributes["last_year_overall"] = (
                self.client.attributes["lastYearOverAll"]
            )
            self._attr_extra_state_attributes["this_year_overall"] = (
                self.client.attributes["thisYearOverAll"]
            )
            self._attr_extra_state_attributes["history"] = {}
            for item in self.client.attributes["history"]:
                self._attr_extra_state_attributes["history"][item] = (
                    self.client.attributes["history"][item]
                )
            self._attr_extra_state_attributes["deprecated"] = (
                "This sensor is deprecated and will be removed in a future version.\nPlease move to another provided sensor, if you need access to some of the extra attributes let us know and will make them available as sensors."
            )

        except PySuezError:
            self._attr_available = False
            _LOGGER.warning("Unable to fetch data")

    def update(self) -> None:
        """Return the latest collected data from Suez."""
        self._fetch_data()
        _LOGGER.debug("Suez data state is: %s", self.native_value)

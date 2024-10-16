"""Suez water update coordinator."""

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast

from pysuez import SuezData
from pysuez.async_client import SuezAsyncClient
from pysuez.client import PySuezError
from pysuez.suez_data import AlertResult, ConsumptionIndexResult, DayDataResult
import pytz

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import _LOGGER, HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from ..toon.const import CURRENCY_EUR


class SuezWaterCoordinator(DataUpdateCoordinator):
    """Suez water coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_client: SuezAsyncClient,
        data_api: SuezData,
        counter_id: int,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=12),
            always_update=True,
        )
        self._async_client = async_client
        self._data_api: SuezData = data_api
        self._last_day: None | DayDataResult = None
        self._price: None | float = None
        self.alerts: None | AlertResult = None
        self.index: None | ConsumptionIndexResult = None
        self._statistic_id = f"{DOMAIN}:{counter_id}_water_consumption_v2"
        self.config_entry.async_on_unload(self._clear_statistics)
        _LOGGER.debug("Created coordinator")

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        async with asyncio.timeout(20):
            if not await self._async_client.check_credentials():
                raise ConfigEntryError
            await self._async_client.close_session()

    @property
    def consumption_last_day(self) -> DayDataResult | None:
        """Return last day consumption."""
        return self._last_day

    @property
    def price(self) -> float | None:
        """Return water price per m3."""
        return self._price

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            async with asyncio.timeout(200):
                await self._fetch_last_day_consumption_data()
                await self._fetch_consumption_index()
                await self._fetch_price()
                await self._fetch_alerts()
                await self._update_historical()
                await self._async_client.close_session()
                _LOGGER.warning("Suez update completed")
                return {"update": datetime.now()}
        except PySuezError as err:
            raise UpdateFailed(
                f"Suez coordinator error communicating with API: {err}"
            ) from err

    async def _fetch_last_day_consumption_data(self) -> None:
        last_day = await self._data_api.fetch_yesterday_data()
        self._last_day = last_day
        _LOGGER.debug("updated suez water consumption data")

    async def _fetch_consumption_index(self) -> None:
        index = await self._data_api.get_consumption_index()
        if index is None:
            self.index = None
        else:
            self.index = index
        _LOGGER.debug("updated suez water consumption index")

    async def _fetch_price(self) -> None:
        price = await self._data_api.get_price()
        if price is None:
            self._price = None
        else:
            self._price = price.price
        _LOGGER.debug("updated suez water price")

    async def _fetch_alerts(self) -> None:
        self.alerts = await self._data_api.get_alerts()

    async def _update_historical(self) -> None:
        _LOGGER.warning("Updating statistics for %s", self._statistic_id)
        cost_stat_id = self._statistic_id + "_cost"

        last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, self._statistic_id, True, {"sum"}
            )
        cost_last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, cost_stat_id, True, {"sum"}
            )
        usage: list[DayDataResult]
        try:
            last_stats_time: date | None
            if last_stat is None or len(last_stat) == 0:
                    _LOGGER.debug("Updating suez statistic for the first time")
                    usage = await self._data_api.fetch_all_available()
                    consumption_sum = 0.0
                    cost_sum = 0.0
                    last_stats_time = None
            else:
                    previous_stat: StatisticsRow = last_stat[self._statistic_id][0]
                    previous_cost_stat: StatisticsRow = cost_last_stat[cost_stat_id][0]
                    last_stats_time = datetime.fromtimestamp(previous_stat["start"]).date()
                    _LOGGER.debug("Updating suez stat since %s for %s", str(last_stats_time), previous_stat)
                    usage = await self._data_api.fetch_all_available(
                        since=last_stats_time,
                    )
                    if usage is None or len(usage) <= 0:
                        _LOGGER.debug("No recent usage data. Skipping update")
                        return
                    consumption_sum = cast(float, previous_stat["sum"])
                    cost_sum = cast(float, previous_cost_stat["sum"])
        except Exception as err:
            _LOGGER.error("Error while fetching historical data, %s", err)
            raise err
        _LOGGER.debug("fetched data: %s", len(usage))

        consumption_statistics = []
        cost_statistics = []

        for data in usage:
            if last_stats_time is not None and data.date <= last_stats_time:
                continue
            consumption_sum += data.day_consumption
            consumption_statistics.append(
                StatisticData(
                    start=datetime.combine(data.date, time(0,0,0,0), pytz.timezone('Europe/Paris')), state=data.day_consumption, sum=consumption_sum
                )
            )
            day_cost = (data.day_consumption / 1000) * self._price
            cost_sum = cost_sum + day_cost
            cost_statistics.append(
                StatisticData(
                    start=datetime.combine(data.date, time(0,0,0,0), pytz.timezone('Europe/Paris')), state=day_cost, sum=cost_sum
                )
            )

        consumption_metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{self._statistic_id} Consumption",
            source=DOMAIN,
            statistic_id=self._statistic_id,
            unit_of_measurement=UnitOfVolume.LITERS
        )
        cost_metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{self._statistic_id} Consumption cost",
            source=DOMAIN,
            statistic_id=cost_stat_id,
            unit_of_measurement=CURRENCY_EUR + "/" + UnitOfVolume.LITERS
        )

        _LOGGER.trace(
            "Adding %s statistics for %s",
            len(consumption_statistics),
            self._statistic_id,
        )
        async_add_external_statistics(
            self.hass, consumption_metadata, consumption_statistics
        )
        async_add_external_statistics(
            self.hass, cost_metadata, cost_statistics
        )

        _LOGGER.debug("Updated statistics for %s", self._statistic_id)


    def _clear_statistics(self) -> None:
        """Clear statistics."""
        get_instance(self.hass).async_clear_statistics(list(self._statistic_id))

    def get_attribution(self) -> str:
        """Get attribution message."""
        attr: str = self._data_api.get_attribution()
        return attr

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
        self._statistic_id = f"{DOMAIN}:{counter_id}_water_consumption"
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
                #await self._fetch_last_day_consumption_data()
                #await self._fetch_consumption_index()
                await self._fetch_price()
                #await self._fetch_alerts()
                await self._update_historical()
                await self._async_client.close_session()
                _LOGGER.info("Suez update completed")
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
        _LOGGER.info("Updating statistics for %s", self._statistic_id)

        last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, self._statistic_id, True, set()
            )
        _LOGGER.info("last stat of suez is %s", last_stat)
        usage: list[DayDataResult]
        last_stats_time: date | None
        if not last_stat:
                _LOGGER.debug("Updating statistic for the first time")
                usage = await self._data_api.fetch_all_available()
                consumption_sum = 0.0
                last_stats_time = None
        else:
                previous_stat: StatisticsRow = last_stat[self._statistic_id][0]
                last_stats_time = datetime.fromtimestamp(previous_stat["start"]).date()
                usage = await self._data_api.fetch_all_available(
                    since=last_stats_time,
                )
                if usage is None or len(usage) <= 0:
                    _LOGGER.debug("No recent usage data. Skipping update")
                    return
                consumption_sum = cast(float, previous_stat.sum)
        _LOGGER.info("last saved stat of suez is " +  str(consumption_sum) + " / " +  str(last_stats_time))
        _LOGGER.info("fetched data: %s", len(usage))

        consumption_statistics = []

        _LOGGER.warning(f"{pytz.timezone('Europe/Paris')!s}")

        for data in usage:
            if last_stats_time is not None and data.date <= last_stats_time:
                continue
            consumption_sum += data.day_consumption
            consumption_statistics.append(
                StatisticData(
                    start=datetime.combine(data.date, time(0,0,0,0), pytz.timezone('Europe/Paris')), state=data.day_consumption, sum=consumption_sum
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

        _LOGGER.info(
            "Adding %s statistics for %s",
            len(consumption_statistics),
            self._statistic_id,
        )
        async_add_external_statistics(
            self.hass, consumption_metadata, consumption_statistics
        )

        _LOGGER.info("Updated statistics for %s", self._statistic_id)


    def _clear_statistics(self) -> None:
        """Clear statistics."""
        get_instance(self.hass).async_clear_statistics(list(self._statistic_id))

    def get_attribution(self) -> str:
        """Get attribution message."""
        attr: str = self._data_api.get_attribution()
        return attr

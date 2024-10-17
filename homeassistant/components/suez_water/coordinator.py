"""Suez water update coordinator."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from pysuez import SuezData
from pysuez.async_client import SuezAsyncClient
from pysuez.client import PySuezError
from pysuez.suez_data import AlertResult, ConsumptionIndexResult, DayDataResult

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
            name=f"{DOMAIN}_{counter_id}",
            update_interval=timedelta(minutes=3),
            always_update=True,
        )
        self._async_client = async_client
        self._data_api: SuezData = data_api
        self._last_day: None | DayDataResult = None
        self._price: None | float = None
        self.alerts: None | AlertResult = None
        self.index: None | ConsumptionIndexResult = None
        _LOGGER.debug("Creating coordinator")

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
            async with asyncio.timeout(60):
                await self._fetch_last_day_consumption_data()
                await self._fetch_consumption_index()
                await self._fetch_price()
                await self._fetch_alerts()
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

    def get_attribution(self) -> str:
        """Get attribution message."""
        attr: str = self._data_api.get_attribution()
        return attr

import asyncio
import logging
from datetime import datetime
from aiohttp import ClientSession
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api.saveecobot.com/output.json"
STATION_ID = "SAVEDNIPRO_xxxxx"

SENSORS = {
    "PM2.5": "PM2.5",
    "PM10": "PM10",
    "Temperature": "Temperature",
    "Humidity": "Humidity",
    "Air Quality Index": "AQI"
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({})

def fetch_station_data(data, station_id):
    """Find station data by ID."""
    return next((item for item in data if item.get("id") == station_id), None)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the custom sensors."""
    async with ClientSession() as session:
        try:
            async with session.get(API_URL) as response:
                response.raise_for_status()
                data = await response.json()

            station_data = fetch_station_data(data, STATION_ID)
            if not station_data:
                _LOGGER.error("Station with ID %s not found", STATION_ID)
                return

            sensors = []
            for pollutant in station_data.get("pollutants", []):
                name = pollutant.get("pol")
                if name in SENSORS:
                    sensors.append(MeteoSensor(pollutant))

            async_add_entities(sensors, update_before_add=True)

        except Exception as e:
            _LOGGER.error("Error setting up platform: %s", e)

class MeteoSensor(Entity):
    """Representation of a sensor."""

    def __init__(self, pollutant):
        self._name = f"meteo_station_{pollutant['pol']}"
        self._value = pollutant.get("value")
        if pollutant["pol"] == "Temperature" and pollutant["unit"] == "Celcius":
            self._unit = "°C"
        else:
            self._unit = pollutant.get("unit")
        self._last_updated = pollutant.get("time")

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._value

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        try:
            last_time = datetime.strptime(self._last_updated, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            last_time = self._last_updated
        return {
            "last_updated": last_time
        }

    async def async_update(self):
        """Update the sensor state."""
        async with ClientSession() as session:
            try:
                async with session.get(API_URL) as response:
                    response.raise_for_status()
                    data = await response.json()

                station_data = fetch_station_data(data, STATION_ID)
                if not station_data:
                    _LOGGER.error("Station with ID %s not found", STATION_ID)
                    return

                for pollutant in station_data.get("pollutants", []):
                    if pollutant.get("pol") == self._name.split("_")[-1]:
                        self._value = pollutant.get("value")
                        self._last_updated = pollutant.get("time")
                        break

            except Exception as e:
                _LOGGER.error("Error updating sensor %s: %s", self._name, e)

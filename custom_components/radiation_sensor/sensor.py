import logging
import requests
from bs4 import BeautifulSoup
from homeassistant.components.sensor import SensorEntity
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

URL = "https://www.saveecobot.com/radiation/misto-kyiv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://saveecobot.com/",
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([RadiationSensor()])

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([RadiationSensor()])

class RadiationSensor(SensorEntity):

    def __init__(self):
        self._state = None
        self._unit_of_measurement = "мкЗв/ч"
        self._last_update = None

    @property
    def name(self):
        return "Kyiv Radiation Level"

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {"last_update": self._last_update}

    @property
    def unit_of_measurement(self):
        return self._unit_of_measurement

    def update(self):
        try:
            response = requests.get(URL, headers=HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            data = soup.find("div", class_="grid grid-cols-12 gap-4 sm:gap-8")
            radiation_value = data.find("div", class_="text-2xl md:text-4xl font-medium").text.strip()
            radiation_last_time = data.find("div", class_="text-sm").text.strip()

            self._state = radiation_value
            self._last_update = radiation_last_time

        except Exception as e:
            _LOGGER.error(f"Data update error: {e}")

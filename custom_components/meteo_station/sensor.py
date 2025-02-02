import logging
import requests
from datetime import timedelta, datetime
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
from statistics import mean

_LOGGER = logging.getLogger(__name__)

DOMAIN = "meteo_saveecobot"
SCAN_INTERVAL = timedelta(minutes=15)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://saveecobot.com/",
}

UNITS = {
    "Temperature": "°C",
    "Humidity": "%",
    "Air Quality Index": "aqi"
}

def setup_platform(hass, config, add_entities, discovery_info=None):
    api_url = "https://api.saveecobot.com/output.json"
    sensor_id = config.get("sensor_id")
    sensor_ids = config.get("sensor_ids")
    city_name = config.get("city_name")

    # Average mode
    if sensor_ids:
        for sensor_type in ["Temperature", "Humidity", "Air Quality Index"]:
            add_entities([
                MeteoSaveEcoBotAverageSensor(
                    api_url=api_url,
                    sensor_ids=sensor_ids,
                    sensor_type=sensor_type
                )
            ], True)
    # Single sensor or city mode
    else:
        data_updater = DataUpdater(api_url, HEADERS)
        data_updater.update()
        sensors = []

        for sensor_data in data_updater.get_data() or []:
            if (sensor_id and sensor_data["id"] == sensor_id) or (city_name and sensor_data["cityName"] == city_name):
                sensors.extend([
                    MeteoSaveEcoBotSensor(data_updater, sensor_data, "Temperature"),
                    MeteoSaveEcoBotSensor(data_updater, sensor_data, "Humidity"),
                    MeteoSaveEcoBotSensor(data_updater, sensor_data, "Air Quality Index"),
                ])

        if sensors:
            add_entities(sensors, True)

class DataUpdater:
    def __init__(self, api_url, headers):
        self._api_url = api_url
        self._headers = headers
        self._data = None

    @Throttle(SCAN_INTERVAL)
    def update(self):
        try:
            response = requests.get(self._api_url, headers=self._headers)
            response.raise_for_status()
            self._data = response.json()
        except Exception as e:
            _LOGGER.error(f"Error updating data: {e}")
            self._data = None

    def get_data(self):
        return self._data

class MeteoSaveEcoBotSensor(Entity):
    def __init__(self, data_updater, sensor_data, sensor_type):
        self._data_updater = data_updater
        self._sensor_data = sensor_data
        self._sensor_type = sensor_type
        self._state = None
        self._last_updated = None

    @property
    def name(self):
        return f"Meteo SaveEcoBot {self._sensor_type}"

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return UNITS[self._sensor_type]

    @property
    def extra_state_attributes(self):
        return {
            "last_updated": self._last_updated,
            "sensor_id": self._sensor_data["id"],
            "city": self._sensor_data["cityName"],
            "station": self._sensor_data["stationName"],
        }

    def update(self):
        self._data_updater.update()
        for sensor_data in self._data_updater.get_data() or []:
            if sensor_data["id"] == self._sensor_data["id"]:
                self._update_from_data(sensor_data)
                break

    def _update_from_data(self, sensor_data):
        pollutants = sensor_data["pollutants"]
        self._state = next((poll["value"] for poll in pollutants if poll["pol"] == self._sensor_type), None)
        time_str = next((poll["time"] for poll in pollutants if poll["pol"] == self._sensor_type), None)
        if time_str:
            time_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            self._last_updated = time_obj.strftime("%Y-%m-%d %H:%M:%S")

class MeteoSaveEcoBotAverageSensor(Entity):
    def __init__(self, api_url, sensor_ids, sensor_type):
        self._api_url = api_url
        self._sensor_ids = sensor_ids
        self._sensor_type = sensor_type
        self._state = None
        self._last_updated = None
        self._headers = HEADERS

    @property
    def name(self):
        return f"Meteo SaveEcoBot Average {self._sensor_type}"

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return UNITS[self._sensor_type]

    @property
    def extra_state_attributes(self):
        return {
            "last_updated": self._last_updated,
            "sensor_ids": self._sensor_ids,
        }

    @Throttle(SCAN_INTERVAL)
    def update(self):
        try:
            response = requests.get(self._api_url, headers=self._headers)
            response.raise_for_status()
            data = response.json()

            values = []
            latest_time = None
            
            for sensor_data in data:
                if sensor_data["id"] in self._sensor_ids:
                    pollutants = sensor_data["pollutants"]
                    value = next((poll["value"] for poll in pollutants if poll["pol"] == self._sensor_type), None)
                    if value is not None:
                        values.append(value)
                        time_str = next((poll["time"] for poll in pollutants if poll["pol"] == self._sensor_type), None)
                        if time_str:
                            time_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                            if (not latest_time) or (time_obj > latest_time):
                                latest_time = time_obj

            if values:
                # If there is one sensor, we take its value, otherwise the average.
                self._state = values[0] if len(values) == 1 else round(mean(values), 2)
                self._last_updated = latest_time.strftime("%Y-%m-%d %H:%M:%S") if latest_time else None
            else:
                self._state = None
                self._last_updated = None

        except Exception as e:
            _LOGGER.error(f"Error updating average value: {e}")

import logging
import aiohttp
import asyncio
import gzip
import json
import zlib
from datetime import datetime, timedelta
from statistics import mean
from typing import Optional, List, Dict, Set
from dateutil.parser import parse as date_parse

from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

DOMAIN = "meteo_saveecobot"
SCAN_INTERVAL = timedelta(minutes=15)
REQUEST_TIMEOUT = 5
CACHE_TTL = timedelta(minutes=5)

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Connection": "keep-alive",
}

UNITS = {
    "Temperature": "°C",
    "Humidity": "%",
    "Air Quality Index": "aqi"
}

class CompressedJSONCache:
    _data = None
    _hash = None
    _last_update = None

    @classmethod
    def update(cls, raw_data: bytes):
        try:
            new_hash = zlib.crc32(raw_data)
            if new_hash != cls._hash:
                try:
                    data = json.loads(gzip.decompress(raw_data))
                except (gzip.BadGzipFile, zlib.error):
                    data = json.loads(raw_data.decode('utf-8'))
                
                cls._data = data
                cls._hash = new_hash
                cls._last_update = datetime.utcnow()
        except Exception as e:
            _LOGGER.error(f"Cache update failed: {str(e)}")

    @classmethod
    def get_data(cls) -> Optional[List[Dict]]:
        if cls._data and datetime.utcnow() - cls._last_update < CACHE_TTL:
            return cls._data
        return None

class APIClient:
    _session = None

    @classmethod
    async def fetch_data(cls) -> Optional[bytes]:
        try:
            if cls._session is None:
                cls._session = aiohttp.ClientSession(auto_decompress=True)

            async with cls._session.get(
                "https://api.saveecobot.com/output.json",
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.read()
        except Exception as e:
            _LOGGER.error(f"API request failed: {str(e)}")
            return None

class BackgroundUpdater:
    _task = None
    _sensors = set()

    @classmethod
    async def start(cls):
        if not cls._task or cls._task.done():
            cls._task = asyncio.create_task(cls._update_loop())

    @classmethod
    async def _update_loop(cls):
        while True:
            try:
                raw_data = await APIClient.fetch_data()
                if raw_data:
                    CompressedJSONCache.update(raw_data)
                    _LOGGER.debug("Data updated, refreshing sensors...")
                    
                    # all sensors
                    for sensor in cls._sensors:
                        await sensor.async_update()
                        
            except Exception as e:
                _LOGGER.error(f"Background update error: {str(e)}")
            
            await asyncio.sleep(SCAN_INTERVAL.total_seconds())

    @classmethod
    def register_sensor(cls, sensor):
        cls._sensors.add(sensor)

    @classmethod
    def unregister_sensor(cls, sensor):
        cls._sensors.discard(sensor)

class BaseSensor(Entity):
    _attr_should_poll = False

    def __init__(self, sensor_type: str):
        self._type = sensor_type
        self._state = None
        self._last_updated = None
        BackgroundUpdater.register_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        BackgroundUpdater.unregister_sensor(self)

    @property
    def name(self) -> str:
        return f"Meteo SaveEcoBot {self._type}"

    @property
    def state(self) -> Optional[float]:
        return self._state

    @property
    def unit_of_measurement(self) -> str:
        return UNITS[self._type]

    @property
    def extra_state_attributes(self) -> Dict[str, any]:
        return {
            "last_updated": self._last_updated,
            "source_sensors": []
        }

    def _update_state(self, value: float, timestamp: str):
        try:
            if self._type == "Temperature":
                self._state = round(value, 1) # после запятой
            else:
                self._state = round(value)
                
            self._last_updated = date_parse(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            _LOGGER.warning(f"State update failed: {str(e)}")

class OptimizedSensor(BaseSensor):
    def __init__(self, identifier: str, sensor_type: str, is_city: bool = False):
        super().__init__(sensor_type)
        self._identifier = identifier
        self._is_city = is_city
        self._source_ids = []

    @property
    def extra_state_attributes(self) -> Dict[str, any]:
        return {
            **super().extra_state_attributes,
            "source_sensors": self._source_ids
        }

    async def async_update(self):
        try:
            self._source_ids = []
            data = CompressedJSONCache.get_data()
            
            if not data:
                raw_data = await APIClient.fetch_data()
                if raw_data:
                    CompressedJSONCache.update(raw_data)
                    data = CompressedJSONCache.get_data()
                else:
                    return

            if data:
                values = []
                latest_time = None
                
                for sensor in data:
                    if (self._is_city and sensor['cityName'] == self._identifier) or \
                       (not self._is_city and sensor['id'] == self._identifier):
                        
                        poll_data = next(
                            (p for p in sensor['pollutants'] if p['pol'] == self._type),
                            None
                        )
                        
                        if poll_data:
                            values.append(poll_data['value'])
                            self._source_ids.append(sensor['id'])
                            
                            if 'time' in poll_data:
                                try:
                                    ts = date_parse(poll_data['time'])
                                    if not latest_time or ts > latest_time:
                                        latest_time = ts
                                except Exception as e:
                                    _LOGGER.debug(f"Invalid time format: {poll_data['time']}")
                
                if values:
                    avg_value = mean(values) if len(values) > 1 else values[0]
                    self._update_state(avg_value, latest_time.isoformat() if latest_time else "")
                    self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Sensor update failed: {str(e)}")

class AggregatedSensor(BaseSensor):
    def __init__(self, sensor_ids: Set[str], sensor_type: str):
        super().__init__(sensor_type)
        self._sensor_ids = sensor_ids
        self._source_ids = []

    @property
    def extra_state_attributes(self) -> Dict[str, any]:
        return {
            **super().extra_state_attributes,
            "source_sensors": self._sensor_ids
        }

    async def async_update(self):
        try:
            self._source_ids = []
            data = CompressedJSONCache.get_data()
            
            if not data:
                raw_data = await APIClient.fetch_data()
                if raw_data:
                    CompressedJSONCache.update(raw_data)
                    data = CompressedJSONCache.get_data()

            if data:
                values = []
                latest_time = None

                for sensor in data:
                    if sensor['id'] in self._sensor_ids:
                        poll_data = next(
                            (p for p in sensor['pollutants'] if p['pol'] == self._type),
                            None
                        )
                        
                        if poll_data:
                            values.append(poll_data['value'])
                            
                            if 'time' in poll_data:
                                try:
                                    ts = date_parse(poll_data['time'])
                                    if not latest_time or ts > latest_time:
                                        latest_time = ts
                                except Exception as e:
                                    _LOGGER.debug(f"Invalid time format: {poll_data['time']}")

                if values:
                    avg = mean(values)
                    self._update_state(avg, latest_time.isoformat() if latest_time else "")
                    self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Aggregated sensor update failed: {str(e)}")

async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    try:
        # Предварительная загрузка данных
        raw_data = await APIClient.fetch_data()
        if raw_data:
            CompressedJSONCache.update(raw_data)
        
        await BackgroundUpdater.start()
        
        sensor_id = config.get("sensor_id")
        sensor_ids = config.get("sensor_ids")
        city_name = config.get("city_name")

        if sensor_ids:
            add_entities([AggregatedSensor(set(sensor_ids), st) for st in UNITS], True)
        else:
            add_entities([OptimizedSensor(sensor_id or city_name, st, bool(city_name)) for st in UNITS], True)

    except Exception as e:
        _LOGGER.error(f"Platform setup failed: {str(e)}")
        raise

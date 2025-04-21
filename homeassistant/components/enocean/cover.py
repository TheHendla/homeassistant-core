"""Support for EnOcean cover sources."""

from __future__ import annotations

import logging
from typing import Any

from enocean.protocol import constants as en
from enocean.utils import combine_hex
import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .entity import EnOceanEntity

_LOGGER = logging.getLogger(__name__)

CONF_SENDER_ID = "sender_id"
CONF_EEP_PROFILE = "eep_profile"  # FJ62NP, FSB14

DEFAULT_NAME = "EnOcean Cover"

PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_EEP_PROFILE, default="FJ62NP"): cv.string,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean light platform."""
    dev_id: list[int] = config[CONF_ID]
    sender_id: list[int] = config[CONF_SENDER_ID]
    dev_name: str = config[CONF_NAME]
    eep_profile: str = config[CONF_EEP_PROFILE]

    add_entities([EnOceanCover(dev_id, sender_id, dev_name, eep_profile)])


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean-based cover device (e.g. shutter)."""

    def __init__(
        self, dev_id: list[int], sender_id: list[int], name: str, eep_profile: str
    ) -> None:
        """Initialize the cover."""
        super().__init__(dev_id, sender_id)
        self._attr_unique_id = str(combine_hex(dev_id))
        self._attr_name = name
        self._attr_device_class = CoverDeviceClass.SHUTTER
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        )
        self._attr_is_closed = False
        self._attr_max_drive_way_seconds = 30
        self._eep_profile = eep_profile

    def open_cover(self, **kwargs: Any) -> None:
        """Send the command to open the cover."""
        _LOGGER.info("Opening cover %s", self.name)
        #        [RORG,    MSB,   LSB (Laufzeit in s),   Command 1=Up 0=Stop 2=Down, LRN   ]
        # up     ['0xa5', '0x0', '0x1c', '0x1', '0x8']
        # stop   ['0xa5', '0x0', '0xff', '0x0', '0x8']
        # down   ['0xa5', '0x0', '0x1c', '0x2', '0x8']
        msb, lsb = self.int_to_2byte(30)
        up_command = 0x01

        self.send_command([en.RORG.BS4, msb, lsb, up_command, 0x08])

        self._attr_is_closed = False
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs: Any) -> None:
        """Send the command to close the cover."""
        _LOGGER.info("Closing cover %s", self.name)
        msb, lsb = self.int_to_2byte(30)
        down_command = 0x02
        self.send_command([en.RORG.BS4, msb, lsb, down_command, 0x08])
        self._attr_is_closed = True
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs: Any) -> None:
        """Send the command to stop the cover."""
        _LOGGER.info("Stopping cover %s", self.name)
        msb, lsb = self.int_to_2byte(255)
        stop_command = 0x00
        self.send_command([en.RORG.BS4, msb, lsb, stop_command, 0x08])

    def value_changed(self, packet):
        """Update the internal state of this device."""
        _LOGGER.debug("got enocean cover callback for %s: %s", self.name, str(packet))
        #        [RORG,    STATUS,   (Laufzeit in s),   Command 1=Up, 2=Down, blocked 0x0a not blocked, 0x0e blocked   ]
        # ack    ['0xa5', '0x1', '0x18', '0x2', '0xa']  ['0x0', '0xff', '0xff', '0xff', '0xff', '0x4f', '0x0']

        if packet.data[0] == en.RORG.BS4:
            status = packet.data[1]
            time_in_sec = packet.data[2]
            direction = packet.data[3]
            control_flag = packet.data[4]
            _LOGGER.debug(
                "got 4BS callback for %s, status: %s, time_in_sec: %s, direction: %s, control_flag: %s",
                self.name,
                status,
                time_in_sec,
                direction,
                control_flag,
            )
            self._attr_max_drive_way_seconds = max(
                self._attr_max_drive_way_seconds, time_in_sec
            )
            self.schedule_update_ha_state()
        elif packet.data[0] == en.RORG.RPS:
            status = packet.data[1]
            _LOGGER.debug("got RPS callback for %s, status: %s", self.name, status)
            self.schedule_update_ha_state()
        else:
            _LOGGER.warning("Cannot determine eep profile")

    def int_to_2byte(self, cover_time_in_seconds):
        """Convert integer to two byte value."""
        msb = (cover_time_in_seconds >> 8) & 0xFF
        lsb = cover_time_in_seconds & 0xFF

        return msb, lsb

    def two_byte_to_int(self, msb, lsb):
        """Convert two byte value to integer."""
        return (msb << 8) | lsb

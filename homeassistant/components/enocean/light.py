"""Support for EnOcean light sources."""

from __future__ import annotations

import logging
import math
from typing import Any

from enocean.protocol import constants as en
from enocean.utils import combine_hex
import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    PLATFORM_SCHEMA as LIGHT_PLATFORM_SCHEMA,
    ColorMode,
    LightEntity,
)
from homeassistant.const import CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .entity import EnOceanEntity

_LOGGER = logging.getLogger(__name__)

CONF_SENDER_ID = "sender_id"
CONF_SEND_EEP_SUB_COMMAND = (
    "send_eep_sub_command"  # 0x01 switch e.g. FSR14-2x, 0x02 dimmer e.g. FUD14
)

DEFAULT_NAME = "EnOcean Light"

PLATFORM_SCHEMA = LIGHT_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SEND_EEP_SUB_COMMAND, default="0x02"): cv.positive_int,
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean light platform."""
    sender_id: list[int] = config[CONF_SENDER_ID]
    dev_name: str = config[CONF_NAME]
    dev_id: list[int] = config[CONF_ID]
    send_eep_sub_command: int = config[CONF_SEND_EEP_SUB_COMMAND]

    add_entities([EnOceanLight(sender_id, dev_id, dev_name, send_eep_sub_command)])


class EnOceanLight(EnOceanEntity, LightEntity):
    """Representation of an EnOcean light source."""

    def __init__(
        self,
        sender_id: list[int],
        dev_id: list[int],
        dev_name: str,
        send_eep_sub_command: int,
    ) -> None:
        """Initialize the EnOcean light source."""
        super().__init__(dev_id)
        self._sender_id = sender_id
        self._attr_unique_id = str(combine_hex(dev_id))
        self._attr_name = dev_name
        self._send_eep_sub_command = send_eep_sub_command
        self._attr_is_on = False
        if send_eep_sub_command == 0x01:
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_brightness = 50

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the light source on or sets a specific dimmer value."""
        _LOGGER.info("Turn on")
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = brightness

            bval = math.floor(self._attr_brightness / 256.0 * 100.0)
            if bval == 0:
                bval = 1
            dim_speed = 1
        else:
            bval = 0
            dim_speed = 0

        # FUD14    [ORG 0x07, SUB_COMMAND 0x02, DIM_VALUE, DIM_SPEED, ON 0x09 OFF 0x08]
        # FSR14-2x [ORG 0x07, SUB_COMMAND 0x01, UNUSED, UNUSED, ON 0x09 OFF 0x08]

        command = [en.RORG.BS4, self._send_eep_sub_command, bval, dim_speed, 0x09]
        command.extend(self._sender_id)
        command.extend([0x00])
        self.send_command(command, [], en.PACKET.RADIO)
        self._attr_is_on = True

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the light source off."""
        command = [en.RORG.BS4, self._send_eep_sub_command, 0x00, 0x00, 0x08]
        command.extend(self._sender_id)
        command.extend([0x00])
        self.send_command(command, [], en.PACKET.RADIO)
        self._attr_is_on = False

    def value_changed(self, packet):
        """Update the internal state of this device.

        Dimmer devices like Eltako FUD61 send telegram in different RORGs.
        We only care about the 4BS (0xA5).
        """
        _LOGGER.debug("got enocean callback for %s: %s", self.name, str(packet))
        if packet.data[0] == en.RORG.BS4 and packet.data[1] == 0x02:
            val = packet.data[2]
            self._attr_brightness = math.floor(val / 100.0 * 256.0)
            self._attr_is_on = bool(val != 0)
            self.schedule_update_ha_state()
        elif packet.data[0] == en.RORG.RPS and packet.data[1] == 0x50:
            self._attr_is_on = False
            self.schedule_update_ha_state()
        elif packet.data[0] == en.RORG.RPS and packet.data[1] == 0x70:
            self._attr_is_on = True
            self.schedule_update_ha_state()

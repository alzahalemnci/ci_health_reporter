"""
HA Health Reporter — Home Assistant Custom Integration

Periodically gathers health data (battery levels, offline entities,
automation states) and POSTs a JSON summary to a configured HTTP server.

Configuration (configuration.yaml):

    ha_health_reporter:
      server_url: "http://192.168.1.189"
      server_port: 8765
      interval: 60        # seconds between reports (default: 60)
"""

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_INTERVAL,
    CONF_SERVER_PORT,
    CONF_SERVER_URL,
    DEFAULT_INTERVAL,
    DEFAULT_SERVER_PORT,
    DOMAIN,
)
from .coordinator import HealthReporterCoordinator

_LOGGER = logging.getLogger(__name__)

# Schema for the ha_health_reporter: block in configuration.yaml
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_SERVER_URL): cv.url,
                vol.Optional(CONF_SERVER_PORT, default=DEFAULT_SERVER_PORT): cv.port,
                vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): vol.All(
                    cv.positive_int, vol.Range(min=10)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Set up the HA Health Reporter integration.

    Called by HA when it processes configuration.yaml.
    Instantiates the coordinator and registers a time-interval callback
    that fires the health report on the configured schedule.
    """
    conf = config.get(DOMAIN)
    if conf is None:
        # Integration is installed but not configured — nothing to do
        return True

    server_url: str = conf[CONF_SERVER_URL]
    server_port: int = conf[CONF_SERVER_PORT]
    interval: int = conf[CONF_INTERVAL]

    _LOGGER.info(
        "HA Health Reporter: starting — reporting to %s:%s every %ss",
        server_url,
        server_port,
        interval,
    )

    coordinator = HealthReporterCoordinator(hass, server_url, server_port)

    # Store coordinator so it can be accessed by other parts of the integration
    hass.data[DOMAIN] = coordinator

    # Fire an immediate report when HA finishes starting up
    async def _send_initial_report(event=None):
        await coordinator.async_update()

    hass.bus.async_listen_once("homeassistant_start", _send_initial_report)

    # Schedule recurring reports
    cancel_interval = async_track_time_interval(
        hass,
        coordinator.async_update,
        timedelta(seconds=interval),
    )

    # Clean up the interval listener when HA shuts down
    async def _on_stop(event):
        cancel_interval()
        _LOGGER.info("HA Health Reporter: stopped")

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)

    return True

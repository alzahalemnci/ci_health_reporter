"""
Data coordinator for HA Health Reporter.

Responsible for:
  - Querying all relevant entity states from the HA state machine
  - Assembling a structured JSON health payload
  - HTTP POSTing the payload to the configured server
"""

import logging
from datetime import datetime

import aiohttp
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_LOW_BATTERY_THRESHOLD,
    HEALTH_ENDPOINT_PATH,
    HTTP_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

try:
    import homeassistant as _ha_module
    HA_VERSION = _ha_module.__version__
except Exception:
    HA_VERSION = "unknown"


class HealthReporterCoordinator:
    """
    Gathers HA health data and pushes it to a remote HTTP server.

    This class is intentionally kept simple — it does not subclass
    DataUpdateCoordinator because there are no HA entity subscribers.
    Scheduling is handled externally via async_track_time_interval.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        server_url: str,
        server_port: int,
        low_battery_threshold: int = DEFAULT_LOW_BATTERY_THRESHOLD,
    ) -> None:
        self.hass = hass
        self._url = f"{server_url}:{server_port}{HEALTH_ENDPOINT_PATH}"
        self._low_battery_threshold = low_battery_threshold

    # ------------------------------------------------------------------
    # Public entry point — called by async_track_time_interval
    # ------------------------------------------------------------------

    async def async_update(self, now=None) -> None:
        """Gather health data and push to the configured server."""
        _LOGGER.debug("HA Health Reporter: starting update")
        payload = self._build_payload()
        await self._post_payload(payload)

    # ------------------------------------------------------------------
    # Payload assembly
    # ------------------------------------------------------------------

    def _build_payload(self) -> dict:
        """
        Query the HA state machine and build the full health payload.

        hass.states.async_all() is a synchronous @callback — safe to call
        directly from the event loop. We call it once and filter locally
        to avoid redundant iterations.
        """
        all_states = self.hass.states.async_all()

        batteries = self._gather_batteries(all_states)
        offline = self._gather_offline(all_states)
        automations = self._gather_automations()

        low_batteries = [b for b in batteries if b["low"]]

        return {
            "timestamp": dt_util.utcnow().isoformat(),
            "ha_version": HA_VERSION,
            "batteries": batteries,
            "offline_entities": offline,
            "automations": automations,
            "summary": {
                "battery_count": len(batteries),
                "low_battery_count": len(low_batteries),
                "low_battery_entities": [b["entity_id"] for b in low_batteries],
                "offline_count": len(offline),
                "automation_count": len(automations),
                "automations_enabled": sum(1 for a in automations if a["enabled"]),
                "automations_disabled": sum(1 for a in automations if not a["enabled"]),
            },
        }

    def _gather_batteries(self, all_states: list) -> list:
        """
        Collect battery-level data from all entities.

        Covers two common patterns:
          1. Sensors with device_class == "battery" (numeric state = level)
          2. Entities with a "battery_level" attribute (device trackers, etc.)

        Entities are deduplicated by entity_id so a sensor that matches both
        patterns is only included once.
        """
        seen: set[str] = set()
        batteries: list[dict] = []

        for state in all_states:
            entity_id = state.entity_id
            level: float | None = None

            # Pattern 1: device_class battery sensor
            if state.attributes.get("device_class") == "battery":
                try:
                    level = float(state.state)
                except (ValueError, TypeError):
                    pass  # unavailable / unknown state — skip

            # Pattern 2: battery_level attribute (only if not already captured)
            if level is None and "battery_level" in state.attributes:
                try:
                    level = float(state.attributes["battery_level"])
                except (ValueError, TypeError):
                    pass

            if level is None or entity_id in seen:
                continue

            seen.add(entity_id)
            batteries.append(
                {
                    "entity_id": entity_id,
                    "friendly_name": state.attributes.get("friendly_name", entity_id),
                    "level": level,
                    "unit": state.attributes.get("unit_of_measurement", "%"),
                    "low": level <= self._low_battery_threshold,
                }
            )

        return batteries

    def _gather_offline(self, all_states: list) -> list:
        """
        Collect entities whose state is 'unavailable' or 'unknown'.

        These represent sensors/devices that HA cannot currently reach.
        """
        offline = []
        for state in all_states:
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                offline.append(
                    {
                        "entity_id": state.entity_id,
                        "friendly_name": state.attributes.get(
                            "friendly_name", state.entity_id
                        ),
                        "state": state.state,
                        "domain": state.domain,
                        "last_updated": state.last_updated.isoformat()
                        if state.last_updated
                        else None,
                    }
                )
        return offline

    def _gather_automations(self) -> list:
        """
        Collect the status of all HA automations.

        Reports whether each automation is enabled/disabled and when it
        last ran. The 'last_triggered' attribute is a datetime object
        (or None if the automation has never been triggered).
        """
        automations = []
        for state in self.hass.states.async_all("automation"):
            last_triggered = state.attributes.get("last_triggered")

            # last_triggered may be a datetime object or an ISO string depending
            # on HA version — normalise to string or None
            if isinstance(last_triggered, datetime):
                last_triggered = last_triggered.isoformat()
            elif last_triggered is not None:
                last_triggered = str(last_triggered)

            automations.append(
                {
                    "entity_id": state.entity_id,
                    "friendly_name": state.attributes.get(
                        "friendly_name", state.entity_id
                    ),
                    "enabled": state.state == "on",
                    "last_triggered": last_triggered,
                }
            )
        return automations

    # ------------------------------------------------------------------
    # HTTP POST
    # ------------------------------------------------------------------

    async def _post_payload(self, payload: dict) -> None:
        """POST the health payload to the configured server."""
        session = async_get_clientsession(self.hass)
        try:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
            async with session.post(self._url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    _LOGGER.debug(
                        "Health report sent successfully to %s", self._url
                    )
                else:
                    _LOGGER.warning(
                        "Health Reporter: server returned HTTP %s for %s",
                        resp.status,
                        self._url,
                    )
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Health Reporter: failed to reach server at %s — %s",
                self._url,
                err,
            )

"""
sensor.py — HA sensor entities for the CI Health Reporter dashboard
====================================================================

WHY SENSOR ENTITIES?
---------------------
The integration previously only pushed data to an external HTTP server.
Sensor entities make the same data visible *inside* Home Assistant so it
can be displayed on the Lovelace dashboard, used in automations, and tracked
as long-term statistics.

HOW SENSOR ENTITIES WORK IN HOME ASSISTANT:
---------------------------------------------
An entity is an object that HA keeps track of in its entity registry. Each
entity has:
  - A unique_id: a stable string HA uses to recognise the entity across restarts
  - A name: the human-readable label shown in the UI
  - A state: the current value (a string or number) shown on cards
  - Attributes: extra data attached to the state (a dict); useful for passing
    full data lists to Lovelace markdown cards

HA calls entity.state (or native_value for SensorEntity) whenever it needs
the current value. Because we set _attr_should_poll = False, HA never calls
us on a timer — instead we call schedule_update_ha_state() ourselves whenever
the coordinator has fresh data.

THE PUSH MODEL (listener pattern):
------------------------------------
Each sensor registers a callback with the coordinator via async_add_listener().
When coordinator.async_update() finishes building a new payload, it calls
_notify_listeners(), which calls our _handle_coordinator_update() method,
which calls schedule_update_ha_state().  HA then reads our .native_value and
.extra_state_attributes to get the new values and publishes the updated state.

THE FOUR SENSORS:
-----------------
  sensor.ci_health_low_battery_count    — count of low-battery devices
  sensor.ci_health_offline_count        — count of unavailable/unknown entities
  sensor.ci_health_disabled_automations — count of disabled automations
  sensor.ci_health_system_health        — overall health score (0-100 %)
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HealthReporterCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PLATFORM SETUP
# ---------------------------------------------------------------------------
# HA calls this function when it loads our sensor platform.
# The name must be exactly "async_setup_platform" — HA looks for this name.
#
# Parameters:
#   hass              → the HomeAssistant instance
#   config            → the full configuration.yaml dict (we don't need it here;
#                       the coordinator is already in hass.data[DOMAIN])
#   async_add_entities → callable we use to register our sensor entities with HA
#   discovery_info    → the dict we passed as the third positional arg to
#                       async_load_platform() in __init__.py — empty {} in our case
async def async_setup_platform(
    hass: HomeAssistant,
    config,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
) -> None:
    """Register the CI Health sensor entities with Home Assistant."""

    # Retrieve the coordinator that was stored in __init__.py before this
    # platform was loaded.  If it's missing something went wrong in async_setup.
    coordinator: HealthReporterCoordinator | None = hass.data.get(DOMAIN)
    if coordinator is None:
        _LOGGER.error(
            "CI Health Reporter sensor platform loaded but coordinator not found "
            "in hass.data[%s]. Sensors will not be created.",
            DOMAIN,
        )
        return

    entities = [
        CiHealthLowBatteryCountSensor(coordinator),
        CiHealthOfflineCountSensor(coordinator),
        CiHealthDisabledAutomationsSensor(coordinator),
        CiHealthSystemHealthSensor(coordinator),
    ]

    # update_before_add=False because the coordinator data may already be
    # populated (if the first report fired before this platform loaded).
    # Sensors handle the "no data yet" case by returning None from native_value,
    # which HA displays as "Unknown" — perfectly correct.
    async_add_entities(entities, update_before_add=False)

    _LOGGER.debug(
        "CI Health Reporter: registered %d sensor entities", len(entities)
    )


# ---------------------------------------------------------------------------
# BASE CLASS
# ---------------------------------------------------------------------------

class CiHealthBaseSensor(SensorEntity):
    """
    Shared base for all CI Health sensor entities.

    Handles:
      - Coordinator listener registration (push-based updates)
      - Convenience accessor for coordinator data sub-dicts
    """

    # Tell HA not to call update() on a schedule.
    # We push state changes ourselves via schedule_update_ha_state().
    _attr_should_poll = False

    def __init__(self, coordinator: HealthReporterCoordinator) -> None:
        self._coordinator = coordinator

        # Register our update callback with the coordinator immediately.
        # The coordinator's _notify_listeners() will call _handle_coordinator_update
        # after each data refresh, which tells HA to re-read our state.
        coordinator.async_add_listener(self._handle_coordinator_update)

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Called by the coordinator after each data refresh.

        schedule_update_ha_state() tells HA to call our state properties
        on the next event loop tick and publish the result to the state machine.
        """
        self.schedule_update_ha_state()

    def _summary(self) -> dict:
        """Convenience shorthand for the 'summary' sub-dict of coordinator data."""
        return self._coordinator.data.get("summary", {})


# ---------------------------------------------------------------------------
# SENSOR 1 — Low Battery Count
# ---------------------------------------------------------------------------

class CiHealthLowBatteryCountSensor(CiHealthBaseSensor):
    """
    Reports the number of devices with a battery level at or below the
    low-battery threshold (default 20 %).

    extra_state_attributes provides:
      - low_battery_entities: list of entity IDs with low battery (for alerts)
      - batteries: full list of all battery devices with levels (for the
                   Lovelace battery bar chart)
    """

    # HA stores unique_id in the entity registry.  Must be stable across restarts.
    _attr_unique_id = "ci_health_low_battery_count"

    # Name determines the entity_id: "CI Health Low Battery Count"
    # → sensor.ci_health_low_battery_count
    _attr_name = "CI Health Low Battery Count"

    _attr_icon = "mdi:battery-alert"

    # MEASUREMENT means the value can go up or down freely (unlike TOTAL_INCREASING).
    # Required for HA to store long-term statistics and show history graphs.
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the count of low-battery devices, or None if no data yet."""
        return self._summary().get("low_battery_count")

    @property
    def extra_state_attributes(self) -> dict:
        """
        Return full battery data for use in Lovelace Jinja templates.

        'batteries' contains ALL battery devices (not just low ones) so the
        dashboard can render the full battery-levels bar chart.
        """
        data = self._coordinator.data
        return {
            "low_battery_entities": self._summary().get("low_battery_entities", []),
            "batteries": data.get("batteries", []),
        }


# ---------------------------------------------------------------------------
# SENSOR 2 — Offline Count
# ---------------------------------------------------------------------------

class CiHealthOfflineCountSensor(CiHealthBaseSensor):
    """
    Reports the number of entities currently in the "unavailable" or "unknown"
    state.  These are devices that HA can't reach.

    extra_state_attributes provides:
      - offline_entities: full list of offline entity records (used in the
                          Active Issues panel in the Lovelace dashboard)
    """

    _attr_unique_id   = "ci_health_offline_count"
    _attr_name        = "CI Health Offline Count"
    _attr_icon        = "mdi:wifi-off"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        return self._summary().get("offline_count")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "offline_entities": self._coordinator.data.get("offline_entities", []),
        }


# ---------------------------------------------------------------------------
# SENSOR 3 — Disabled Automations
# ---------------------------------------------------------------------------

class CiHealthDisabledAutomationsSensor(CiHealthBaseSensor):
    """
    Reports the number of automations that are currently disabled (state "off").

    extra_state_attributes provides:
      - disabled_automations: list of disabled automation records
      - automations_enabled:  count of currently enabled automations
      - automation_count:     total automation count
    """

    _attr_unique_id   = "ci_health_disabled_automations"
    _attr_name        = "CI Health Disabled Automations"
    _attr_icon        = "mdi:robot-off"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        return self._summary().get("automations_disabled")

    @property
    def extra_state_attributes(self) -> dict:
        automations = self._coordinator.data.get("automations", [])
        return {
            "disabled_automations": [a for a in automations if not a.get("enabled")],
            "automations_enabled":  self._summary().get("automations_enabled"),
            "automation_count":     self._summary().get("automation_count"),
        }


# ---------------------------------------------------------------------------
# SENSOR 4 — System Health Score
# ---------------------------------------------------------------------------

class CiHealthSystemHealthSensor(CiHealthBaseSensor):
    """
    Reports a 0–100 health score computed from battery, offline, and
    automation issues.  Used for the gauge card and 30-day history graph.

    Score formula (defined in coordinator.py / const.py):
        100  − min(low_battery_count * 5,  30)
             − min(offline_count     * 3,  30)
             − min(disabled_count    * 2,  20)
        clamped to [0, 100]

    extra_state_attributes provides:
      - per-category counts (for the Maintenance Suggestions Jinja template)
      - ha_version and last_updated (for the dashboard footer)
    """

    _attr_unique_id                   = "ci_health_system_health"
    _attr_name                        = "CI Health System Health"
    _attr_icon                        = "mdi:heart-pulse"
    _attr_native_unit_of_measurement  = "%"

    # MEASUREMENT is required so HA records long-term statistics and the
    # history-graph card can show a 30-day trend line.
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        return self._summary().get("system_health")

    @property
    def extra_state_attributes(self) -> dict:
        summary = self._summary()
        data    = self._coordinator.data
        return {
            "low_battery_count":    summary.get("low_battery_count", 0),
            "offline_count":        summary.get("offline_count", 0),
            "automations_disabled": summary.get("automations_disabled", 0),
            # Human-readable names (not entity IDs) for the suggestions template
            "offline_entity_names": [
                e.get("friendly_name", e.get("entity_id", "unknown"))
                for e in data.get("offline_entities", [])
            ],
            "disabled_automation_names": [
                a.get("friendly_name", a.get("entity_id", "unknown"))
                for a in data.get("automations", [])
                if not a.get("enabled")
            ],
            "ha_version":    data.get("ha_version", "unknown"),
            "last_updated":  data.get("timestamp"),
        }

"""Constants for the HA Health Reporter integration."""

DOMAIN = "ha_health_reporter"

# Configuration keys (used in configuration.yaml)
CONF_SERVER_URL = "server_url"
CONF_SERVER_PORT = "server_port"
CONF_INTERVAL = "interval"

# Defaults
DEFAULT_INTERVAL = 60          # seconds — 1 minute for testing
DEFAULT_SERVER_PORT = 8765
DEFAULT_LOW_BATTERY_THRESHOLD = 20  # percent; batteries at or below this are flagged

# HTTP
HEALTH_ENDPOINT_PATH = "/health"
HTTP_TIMEOUT_SECONDS = 10

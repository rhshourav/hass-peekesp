"""Constants for the PeekESP integration.

Nothing in here imports Home Assistant, so tests/test_core.py can load it alone.
"""

DOMAIN = "peekesp"

# Relay offered in the pairing form. No trailing slash: the config flow appends
# /telemetry/<stream>. It must be the relay the device itself is pointed at.
DEFAULT_RELAY_BASE = "https://peek-relay-b9a8.onrender.com"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_CODE = "code"
CONF_RELAY_BASE = "relay_base"
CONF_MODE = "mode"
CONF_REGENERATE = "regenerate"
MODE_PAIRED = "paired"
MODE_MANUAL = "manual"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_OFFLINE_AFTER = "offline_after"

# The device polls every 5 s by default. HA polls the same endpoint, so every
# second here is a request against the same Worker quota.
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600
# The firmware calls a machine offline after poll_s * 5 (25 s at defaults).
DEFAULT_OFFLINE_AFTER = 30
MIN_OFFLINE_AFTER = 10
MAX_OFFLINE_AFTER = 3600

CARD_URL = "/peekesp_static/peekesp-card.js"

# --- where to find the project ----------------------------------------------
URL_GITHUB_PROFILE = "https://github.com/rhshourav"
URL_REPO_MAIN = "https://github.com/rhshourav/PeekESP"
URL_REPO_HA = "https://github.com/rhshourav/hass-peekesp"
URL_DISCORD = "https://discord.gg/nHtHMmjzRU"

# The keys are used three ways, so renaming one means renaming it everywhere:
# as {placeholders} in strings.json (Home Assistant wants URLs passed in rather
# than written into a translation), as the dialogs' description_placeholders,
# and as the response keys of the peekesp.get_links action.
LINKS: dict[str, str] = {
    "github_profile": URL_GITHUB_PROFILE,
    "repo_main": URL_REPO_MAIN,
    "repo_ha": URL_REPO_HA,
    "discord": URL_DISCORD,
}

# --- actions ----------------------------------------------------------------
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_NOTIFY = "notify"
ATTR_STORE_CODE = "store_code"

SERVICE_GENERATE_PAIRING_CODE = "generate_pairing_code"
SERVICE_GET_PAIRING_CODE = "get_pairing_code"
SERVICE_ROTATE_PAIRING_CODE = "rotate_pairing_code"
SERVICE_GET_LINKS = "get_links"
SERVICE_REFRESH = "refresh"
SERVICE_SET_OPTIONS = "set_options"
SERVICE_PAIR = "pair"
SERVICE_ADD_CUSTOM_RELAY = "add_custom_relay"

"""Runs the config flow, options flow, actions and entities inside Home Assistant.

    pip install pytest-homeassistant-custom-component
    pytest tests/test_ha.py

Skipped, not failed, where that package is not installed: test_core.py is the
Home-Assistant-free half and needs nothing.
"""
import json
import pathlib
import sys
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.components import persistent_notification  # noqa: E402
from homeassistant.core import Context  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.exceptions import (  # noqa: E402
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
    mock_component,
)

from custom_components.peekesp import services as svc  # noqa: E402
from custom_components.peekesp.api import (  # noqa: E402
    Machine,
    PeekAuthError,
    PeekConnectionError,
    RelayData,
)
from custom_components.peekesp.const import (  # noqa: E402
    CONF_CODE,
    CONF_MODE,
    CONF_RELAY_BASE,
    CONF_REGENERATE,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_RELAY_BASE,
    DOMAIN,
    LINKS,
    MODE_MANUAL,
    MODE_PAIRED,
    URL_REPO_MAIN,
)
from custom_components.peekesp.pairing import derive, format_code, is_valid_code, new_code  # noqa: E402

PKG = ROOT / "custom_components" / "peekesp"
FETCH = "custom_components.peekesp.api.PeekRelayClient.fetch"
CARD = "custom_components.peekesp._register_card"


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Let Home Assistant see custom_components/peekesp."""


@pytest.fixture(autouse=True)
def _no_card(hass):
    """The Lovelace card needs the http and frontend components (manifest
    dependencies); it is covered by tests/test_card.js, not here. They are
    marked as already set up rather than pulling in the real frontend bundle."""
    mock_component(hass, "http")
    mock_component(hass, "frontend")
    with patch(CARD, new=AsyncMock()):
        yield


def _data(*hosts: str) -> RelayData:
    return RelayData(
        machines={h: Machine(host=h, cpu_percent=12.5, ram_percent=40.0, age_s=2) for h in hosts},
        latency_ms=42,
        fetched_at=1.0,
    )


def _entry(**data) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=data, unique_id=data.get("uid", "u"), title="PeekESP t")


def _generated_entry(code: str = "K7M2P4QX9R", options: dict | None = None) -> MockConfigEntry:
    stream, token = derive(code)
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=stream,
        title=f"PeekESP {stream[:6]}",
        options=options or {},
        data={
            CONF_MODE: MODE_PAIRED,
            CONF_URL: f"{DEFAULT_RELAY_BASE}/telemetry/{stream}",
            CONF_TOKEN: token,
            CONF_CODE: code,
        },
    )


def _entered_entry(code: str = "K7M2P4QX9R") -> MockConfigEntry:
    stream, token = derive(code)
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=stream,
        title=f"PeekESP {stream[:6]}",
        data={
            CONF_MODE: MODE_PAIRED,
            CONF_URL: f"{DEFAULT_RELAY_BASE}/telemetry/{stream}",
            CONF_TOKEN: token,
        },
    )


def _links_note(hass):
    """Persistent notifications are a plain dict, not entities, since 2023.6."""
    return persistent_notification._async_get_or_create_notifications(hass).get(svc.NOTIFICATION_ID)


async def _setup(hass, entry, *hosts):
    entry.add_to_hass(hass)
    with patch(FETCH, AsyncMock(return_value=_data(*hosts))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


# ---------------------------------------------------------------------------
#  Setup flow
# ---------------------------------------------------------------------------
async def test_setup_menu_offers_generate_and_links(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] is FlowResultType.MENU
    assert r["menu_options"] == ["pair", "generate", "manual", "links"]


async def test_links_step_carries_every_url_and_goes_back(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "links"})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "links"
    assert r["description_placeholders"] == LINKS
    # The four things asked for: profile, repository (both), Discord.
    assert LINKS["github_profile"] == "https://github.com/rhshourav"
    assert LINKS["repo_main"] == "https://github.com/rhshourav/PeekESP"
    assert LINKS["repo_ha"] == "https://github.com/rhshourav/hass-peekesp"
    assert LINKS["discord"] == "https://discord.gg/nHtHMmjzRU"
    # "Back" lands on the main menu again rather than ending the flow.
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "user"})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "user"


async def _open_generate(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "generate"})


async def test_generate_shows_a_valid_code_in_device_format(hass):
    r = await _open_generate(hass)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "generate"
    shown = r["description_placeholders"]["code"]
    assert len(shown) == 12 and shown[4] == "-" and shown[9] == "-"  # K7M2-P4QX-9R
    assert is_valid_code(shown.replace("-", ""))


async def test_generate_creates_entry_and_keeps_the_code(hass):
    r = await _open_generate(hass)
    shown = r["description_placeholders"]["code"]
    code = shown.replace("-", "")
    stream, token = derive(code)
    with patch(FETCH, AsyncMock(return_value=RelayData())), patch(
        "custom_components.peekesp.async_setup_entry", AsyncMock(return_value=True)
    ):
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_RELAY_BASE: DEFAULT_RELAY_BASE, CONF_REGENERATE: False}
        )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"] == {
        CONF_MODE: MODE_PAIRED,
        CONF_URL: f"{DEFAULT_RELAY_BASE}/telemetry/{stream}",
        CONF_TOKEN: token,
        CONF_CODE: code,  # the code on screen is the code that was saved
    }
    assert r["result"].unique_id == stream


async def test_generate_flow_end_to_end_with_real_setup(hass):
    """No patched setup: the entry the flow makes actually loads and works."""
    r = await _open_generate(hass)
    code = r["description_placeholders"]["code"].replace("-", "")
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_RELAY_BASE: DEFAULT_RELAY_BASE, CONF_REGENERATE: False}
        )
        await hass.async_block_till_done()
    entry = r["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_CODE] == code
    assert hass.states.get("sensor.desk_cpu") is not None
    assert hass.states.get("button.peekesp_relay_refresh_now") is not None
    # And the action hands back exactly what the dialog showed.
    assert (await _call(hass, "get_pairing_code"))["code"] == code


async def test_generate_regenerate_gives_a_new_code_and_saves_nothing(hass):
    r = await _open_generate(hass)
    first = r["description_placeholders"]["code"]
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_RELAY_BASE: DEFAULT_RELAY_BASE, CONF_REGENERATE: True}
    )
    assert r["type"] is FlowResultType.FORM
    assert r["description_placeholders"]["code"] != first
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_generate_keeps_the_same_code_across_an_error(hass):
    r = await _open_generate(hass)
    shown = r["description_placeholders"]["code"]
    with patch(FETCH, AsyncMock(side_effect=PeekConnectionError("down"))):
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_RELAY_BASE: DEFAULT_RELAY_BASE, CONF_REGENERATE: False}
        )
    assert r["errors"] == {"base": "cannot_connect"}
    # A code someone may already have copied must not change under them.
    assert r["description_placeholders"]["code"] == shown


async def test_generate_rejects_plain_http(hass):
    r = await _open_generate(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_RELAY_BASE: "http://relay.example", CONF_REGENERATE: False}
    )
    assert r["errors"] == {CONF_RELAY_BASE: "invalid_url"}


async def test_entering_a_code_does_not_store_it(hass):
    """Least privilege: the code can push and command, the read token cannot."""
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "pair"})
    with patch(FETCH, AsyncMock(return_value=RelayData())), patch(
        "custom_components.peekesp.async_setup_entry", AsyncMock(return_value=True)
    ):
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {"code": "k7m2-p4qx-9r", CONF_RELAY_BASE: DEFAULT_RELAY_BASE}
        )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_CODE not in r["data"]
    assert r["data"][CONF_TOKEN] == "ec3cb3699bd1284efb2fcfe056609e87edf4813b84e9ce84"


async def test_reauth_drops_a_stale_generated_code(hass):
    entry = _generated_entry()
    entry.add_to_hass(hass)
    r = await entry.start_reauth_flow(hass)
    assert r["step_id"] == "reauth_confirm"
    with patch(FETCH, AsyncMock(return_value=RelayData())), patch(
        "custom_components.peekesp.async_setup_entry", AsyncMock(return_value=True)
    ):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_CODE: "AAAA-BBBB-CC"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reauth_successful"
    assert CONF_CODE not in entry.data  # not left showing a code that no longer applies
    assert entry.data[CONF_TOKEN] == derive("AAAABBBBCC")[1]


# ---------------------------------------------------------------------------
#  Options flow
# ---------------------------------------------------------------------------
async def test_options_menu_and_settings_still_work(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    assert r["menu_options"] == ["settings", "pairing_code", "links"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "settings"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "settings"
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"scan_interval": 20, "offline_after": 60}
        )
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 20, "offline_after": 60}


async def test_options_links(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "links"})
    assert r["step_id"] == "links" and r["description_placeholders"] == LINKS
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "init"})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "init"


async def test_options_shows_the_generated_code_and_device_values(hass):
    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "pairing_code"})
    assert r["step_id"] == "pairing_code"
    ph = r["description_placeholders"]
    assert ph["code"] == "K7M2-P4QX-9R"
    assert ph["read_token"] == "ec3cb3699bd1284efb2fcfe056609e87edf4813b84e9ce84"
    assert ph["worker_url"] == "https://peek-relay-b9a8.onrender.com/telemetry/4b907ba136d0a7f2"


async def test_options_is_honest_when_the_code_was_typed_in(hass):
    entry = _entered_entry()
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "pairing_code"})
    assert r["type"] is FlowResultType.MENU and r["step_id"] == "pairing_unknown"
    assert r["menu_options"] == ["rotate_code", "init"]  # "Back" last, as menus usually do
    # What the ESP32's setup page needs is still there, because it was kept.
    assert r["description_placeholders"]["read_token"] == derive("K7M2P4QX9R")[1]
    assert "code" not in (r.get("description_placeholders") or {})
    # ...and a person can still get a code from here.
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "rotate_code"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "rotate_code"


async def test_options_hides_pairing_for_a_custom_relay(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="m", title="PeekESP (custom relay)",
        data={CONF_MODE: MODE_MANUAL, CONF_URL: "https://x.example/telemetry/s", CONF_TOKEN: "t"},
    )
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["menu_options"] == ["settings", "links"]


async def test_rotate_switches_the_entry_to_a_new_code(hass):
    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    old_stream = entry.unique_id
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "pairing_code"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "rotate_code"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "rotate_code"
    shown = r["description_placeholders"]["code"]
    assert shown.replace("-", "") != "K7M2P4QX9R"

    # Nothing changes until it is submitted.
    assert entry.data[CONF_CODE] == "K7M2P4QX9R" and entry.unique_id == old_stream

    new = shown.replace("-", "")
    stream, token = derive(new)
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_REGENERATE: False})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_CODE] == new
    assert entry.data[CONF_TOKEN] == token
    assert entry.data[CONF_URL] == f"{DEFAULT_RELAY_BASE}/telemetry/{stream}"
    assert entry.unique_id == stream
    assert entry.title == f"PeekESP {stream[:6]}"  # still the auto name, so it follows
    assert entry.state is ConfigEntryState.LOADED  # reloaded onto the new stream


async def test_rotate_regenerate_and_errors_change_nothing(hass):
    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "pairing_code"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "rotate_code"})
    first = r["description_placeholders"]["code"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_REGENERATE: True})
    assert r["description_placeholders"]["code"] != first
    for exc, key in ((PeekConnectionError("x"), "cannot_connect"), (PeekAuthError("x"), "invalid_auth")):
        with patch(FETCH, AsyncMock(side_effect=exc)):
            r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_REGENERATE: False})
        assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": key}
    assert entry.data[CONF_CODE] == "K7M2P4QX9R"


async def test_rotate_keeps_a_title_the_user_renamed(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    hass.config_entries.async_update_entry(entry, title="Workshop")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "pairing_code"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "rotate_code"})
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        await hass.config_entries.options.async_configure(r["flow_id"], {CONF_REGENERATE: False})
        await hass.async_block_till_done()
    assert entry.title == "Workshop"


# ---------------------------------------------------------------------------
#  Entities, devices
# ---------------------------------------------------------------------------
async def test_buttons_and_device_visit_link(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    reg = er.async_get(hass)
    ids = {e.translation_key or e.original_name: e.entity_id
           for e in er.async_entries_for_config_entry(reg, entry.entry_id) if e.domain == "button"}
    assert set(ids) == {"Refresh now", "Show links"}
    dev = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert dev.configuration_url == URL_REPO_MAIN  # the device page's "Visit" button


async def test_refresh_button_polls_and_stays_pressable_when_the_relay_is_down(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    refresh = next(
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.original_name == "Refresh now"
    )
    # The relay goes away: the sensors become unavailable, the button must not.
    coordinator = entry.runtime_data
    with patch(FETCH, AsyncMock(side_effect=PeekConnectionError("down"))):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert not coordinator.last_update_success
        assert hass.states.get(refresh).state != "unavailable"

        fetch = AsyncMock(return_value=_data("desk"))
        with patch(FETCH, fetch):
            await hass.services.async_call("button", "press", {"entity_id": refresh}, blocking=True)
            await hass.async_block_till_done()
        assert fetch.await_count >= 1
        assert coordinator.last_update_success


async def test_show_links_button_posts_a_notification(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    links = next(
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.original_name == "Show links"
    )
    await hass.services.async_call("button", "press", {"entity_id": links}, blocking=True)
    await hass.async_block_till_done()
    note = _links_note(hass)
    assert note is not None
    for url in LINKS.values():
        assert url in note["message"]


# ---------------------------------------------------------------------------
#  Actions
# ---------------------------------------------------------------------------
ACTIONS = (
    "generate_pairing_code", "get_pairing_code", "rotate_pairing_code", "get_links",
    "refresh", "set_options", "pair", "add_custom_relay",
)


async def test_actions_exist_once_the_integration_is_loaded_even_with_no_entry(hass):
    """An empty `peekesp:` line in configuration.yaml is how that happens in real
    Home Assistant: without an entry or a YAML key it never runs async_setup."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    for name in ACTIONS:
        assert hass.services.has_service(DOMAIN, name), name
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_the_empty_yaml_key_is_accepted_without_complaint(hass, caplog):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})
    assert "does not support" not in caplog.text


async def _call(hass, name, data=None, *, response=True, context=None):
    return await hass.services.async_call(
        DOMAIN, name, data or {}, blocking=True, return_response=response, context=context
    )


async def test_generate_pairing_code_action(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {})
    a, b = await _call(hass, "generate_pairing_code"), await _call(hass, "generate_pairing_code")
    assert is_valid_code(a["code"]) and a["code_formatted"] == format_code(a["code"])
    assert a["stream_id"] == derive(a["code"])[0]
    assert a["code"] != b["code"]


async def test_get_pairing_code_action(hass):
    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    r = await _call(hass, "get_pairing_code")  # one entry: no id needed
    assert r == {
        "config_entry_id": entry.entry_id, "title": entry.title,
        "code": "K7M2P4QX9R", "code_formatted": "K7M2-P4QX-9R",
    }
    r = await _call(hass, "get_pairing_code", {"config_entry_id": entry.entry_id})
    assert r["code"] == "K7M2P4QX9R"


async def test_get_pairing_code_errors_say_why(hass):
    typed = _entered_entry("AAAABBBBCC")
    await _setup(hass, typed, "desk")
    with pytest.raises(ServiceValidationError) as e:
        await _call(hass, "get_pairing_code")
    assert e.value.translation_key == "no_code_stored"

    other = _generated_entry("K7M2P4QX9R")
    await _setup(hass, other, "desk")
    with pytest.raises(ServiceValidationError) as e:
        await _call(hass, "get_pairing_code")  # two entries, none chosen
    assert e.value.translation_key == "multiple_entries"
    with pytest.raises(ServiceValidationError) as e:
        await _call(hass, "get_pairing_code", {"config_entry_id": "nope"})
    assert e.value.translation_key == "unknown_entry"


async def test_get_pairing_code_is_administrators_only(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    admin = await hass.auth.async_create_user("admin", group_ids=[GROUP_ID_ADMIN])
    member = await hass.auth.async_create_user("member", group_ids=[GROUP_ID_USER])
    assert (await _call(hass, "get_pairing_code", context=Context(user_id=admin.id)))["code"]
    with pytest.raises(Unauthorized):
        await _call(hass, "get_pairing_code", context=Context(user_id=member.id))
    # An automation (no user) is trusted, as for every other admin action.
    assert (await _call(hass, "get_pairing_code"))["code"]


async def test_get_links_action(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {})
    assert await _call(hass, "get_links") == LINKS
    assert _links_note(hass) is None
    assert await _call(hass, "get_links", {"notify": True}) == LINKS
    await hass.async_block_till_done()
    assert _links_note(hass) is not None


async def test_refresh_action(hass):
    # A long poll interval, so the clock jump below fires only the debouncer and
    # not each coordinator's own timer, which would muddy the count.
    slow = {"scan_interval": 600}
    a = _generated_entry("K7M2P4QX9R", slow)
    b = _generated_entry("AAAABBBBCC", slow)
    await _setup(hass, a, "desk")
    await _setup(hass, b, "pi")
    fetch = AsyncMock(return_value=_data("desk"))
    with patch(FETCH, fetch):
        await _call(hass, "refresh", response=False)  # both entries, now
        assert fetch.await_count == 2

        # Straight away again: held back by the coordinator's 10 s cooldown, so a
        # script or a held-down button cannot hammer the shared relay...
        fetch.reset_mock()
        await _call(hass, "refresh", {"config_entry_id": a.entry_id}, response=False)
        await _call(hass, "refresh", {"config_entry_id": a.entry_id}, response=False)
        assert fetch.await_count == 0

        # ...and the requests made meanwhile collapse into one poll afterwards.
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
        await hass.async_block_till_done()
        assert fetch.await_count == 1
    with pytest.raises(ServiceValidationError) as e:
        await _call(hass, "refresh", {"config_entry_id": "nope"}, response=False)
    assert e.value.translation_key == "unknown_entry"


async def test_rotate_pairing_code_action(hass):
    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await _call(hass, "rotate_pairing_code")
        await hass.async_block_till_done()
    assert is_valid_code(r["code"]) and r["code"] != "K7M2P4QX9R"
    stream, token = derive(r["code"])
    assert r["stream_id"] == stream and r["code_formatted"] == format_code(r["code"])
    assert entry.data[CONF_CODE] == r["code"] and entry.data[CONF_TOKEN] == token
    assert entry.data[CONF_URL] == f"{DEFAULT_RELAY_BASE}/telemetry/{stream}"
    assert entry.unique_id == stream and r["title"] == entry.title == f"PeekESP {stream[:6]}"
    assert entry.state is ConfigEntryState.LOADED  # reloaded onto the new stream
    assert (await _call(hass, "get_pairing_code"))["code"] == r["code"]


async def test_rotate_pairing_code_action_errors_change_nothing(hass):
    custom = MockConfigEntry(
        domain=DOMAIN, unique_id="m", title="PeekESP (custom relay)",
        data={CONF_MODE: MODE_MANUAL, CONF_URL: "https://x.example/telemetry/s", CONF_TOKEN: "t"},
    )
    await _setup(hass, custom, "desk")
    with pytest.raises(ServiceValidationError) as e:
        await _call(hass, "rotate_pairing_code")
    assert e.value.translation_key == "not_paired"
    await hass.config_entries.async_remove(custom.entry_id)

    entry = _generated_entry("K7M2P4QX9R")
    await _setup(hass, entry, "desk")
    for exc, key in ((PeekConnectionError("x"), "cannot_connect"), (PeekAuthError("x"), "invalid_auth")):
        with patch(FETCH, AsyncMock(side_effect=exc)), pytest.raises(HomeAssistantError) as e:
            await _call(hass, "rotate_pairing_code")
        assert e.value.translation_key == key
    assert entry.data[CONF_CODE] == "K7M2P4QX9R"


async def test_set_options_action(hass):
    a = _generated_entry("K7M2P4QX9R")
    b = _generated_entry("AAAABBBBCC")
    await _setup(hass, a, "desk")
    await _setup(hass, b, "pi")
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        await _call(hass, "set_options", {"config_entry_id": a.entry_id, "scan_interval": 30}, response=False)
        await hass.async_block_till_done()
        assert a.options == {"scan_interval": 30} and b.options == {}
        assert a.state is ConfigEntryState.LOADED
        assert a.runtime_data.update_interval == timedelta(seconds=30)

        # No entry named: all of them, and what was already set is kept.
        await _call(hass, "set_options", {"offline_after": 90}, response=False)
        await hass.async_block_till_done()
    assert a.options == {"scan_interval": 30, "offline_after": 90}
    assert b.options == {"offline_after": 90}
    assert a.runtime_data.offline_after == 90


async def test_set_options_action_rejects_nonsense(hass):
    import voluptuous as vol

    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    for bad in ({}, {"scan_interval": 1}, {"scan_interval": 601}, {"offline_after": 9},
                {"offline_after": 3601}, {"scan_interval": "fast"}):
        with pytest.raises(vol.Invalid):
            await _call(hass, "set_options", bad, response=False)
    assert entry.options == {}


async def test_pair_action_makes_the_first_entry(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await _call(hass, "pair", {"code": "k7m2-p4qx-9r"})
        await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(r["config_entry_id"])
    assert r["title"] == entry.title == "PeekESP 4b907b"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "4b907ba136d0a7f2"
    assert entry.data[CONF_URL] == f"{DEFAULT_RELAY_BASE}/telemetry/4b907ba136d0a7f2"
    assert entry.data[CONF_TOKEN] == "ec3cb3699bd1284efb2fcfe056609e87edf4813b84e9ce84"
    assert CONF_CODE not in entry.data  # typed in, so not kept, same as the dialog


async def test_pair_action_can_keep_the_code_and_use_another_relay(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        gen = await _call(hass, "generate_pairing_code")
        r = await _call(hass, "pair", {
            "code": gen["code"], "relay_base": "https://mine.example/", "store_code": True,
        })
        await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(r["config_entry_id"])
    assert entry.data[CONF_URL] == f"https://mine.example/telemetry/{gen['stream_id']}"
    assert entry.data[CONF_CODE] == gen["code"]
    assert (await _call(hass, "get_pairing_code"))["code_formatted"] == gen["code_formatted"]


async def test_pair_action_failures_say_why(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    with patch(FETCH, AsyncMock(return_value=RelayData())):
        for data, key in (
            ({"code": "NOPE"}, "invalid_code"),
            ({"code": "K7M2P4QX9R", "relay_base": "http://x.example"}, "invalid_url"),
        ):
            with pytest.raises(ServiceValidationError) as e:
                await _call(hass, "pair", data)
            assert e.value.translation_key == key
    for exc, key in ((PeekConnectionError("x"), "cannot_connect"), (PeekAuthError("x"), "invalid_auth")):
        with patch(FETCH, AsyncMock(side_effect=exc)), pytest.raises(HomeAssistantError) as e:
            await _call(hass, "pair", {"code": "K7M2P4QX9R"})
        assert e.value.translation_key == key
    assert not hass.config_entries.async_entries(DOMAIN)

    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        await _call(hass, "pair", {"code": "K7M2P4QX9R"})
        await hass.async_block_till_done()
        with pytest.raises(ServiceValidationError) as e:
            await _call(hass, "pair", {"code": "k7m2-p4qx-9r"})  # same stream again
    assert e.value.translation_key == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_add_custom_relay_action(hass):
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
    url = "https://x.example/telemetry/mine"
    with patch(FETCH, AsyncMock(return_value=_data("desk"))):
        r = await _call(hass, "add_custom_relay", {"url": url, "token": "tok"})
        await hass.async_block_till_done()
        entry = hass.config_entries.async_get_entry(r["config_entry_id"])
        assert entry.data == {CONF_MODE: MODE_MANUAL, CONF_URL: url, CONF_TOKEN: "tok"}
        assert entry.state is ConfigEntryState.LOADED
        with pytest.raises(ServiceValidationError) as e:
            await _call(hass, "add_custom_relay", {"url": url, "token": "tok"})
        assert e.value.translation_key == "already_configured"
        with pytest.raises(ServiceValidationError) as e:
            await _call(hass, "add_custom_relay", {"url": "http://x.example/t", "token": "t"})
        assert e.value.translation_key == "invalid_url"


async def test_entry_changing_actions_are_administrators_only(hass):
    entry = _generated_entry()
    await _setup(hass, entry, "desk")
    # The first user Home Assistant creates is made the owner, and an owner is an
    # administrator whatever groups they were given, so make that one first.
    await hass.auth.async_create_user("admin", group_ids=[GROUP_ID_ADMIN])
    member = await hass.auth.async_create_user("member", group_ids=[GROUP_ID_USER])
    calls = {
        "get_pairing_code": {},
        "rotate_pairing_code": {},
        "set_options": {"scan_interval": 20},
        "pair": {"code": "AAAABBBBCC"},
        "add_custom_relay": {"url": "https://x.example/telemetry/s", "token": "t"},
    }
    for name, data in calls.items():
        try:
            await _call(hass, name, data, response=name not in ("set_options",),
                        context=Context(user_id=member.id))
        except Unauthorized:
            continue
        raise AssertionError(f"{name} ran for a non-administrator")
    # Nothing got through.
    assert entry.data[CONF_CODE] == "K7M2P4QX9R" and entry.options == {}
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    # The ones that change nothing and reveal nothing stay open to everyone.
    for name in ("generate_pairing_code", "get_links"):
        assert await _call(hass, name, context=Context(user_id=member.id))


async def test_import_flow_is_the_only_new_door(hass):
    """The actions reach the config flow through the import step, so a flow started
    that way with bad data ends with a reason rather than leaving a form open."""
    r = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "import"}, data={CONF_CODE: "nope"}
    )
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "invalid_code"
    assert not hass.config_entries.flow.async_progress()


# ---------------------------------------------------------------------------
#  The files Home Assistant reads
# ---------------------------------------------------------------------------
def test_strings_and_translation_are_the_same_file():
    assert (PKG / "strings.json").read_text() == (PKG / "translations" / "en.json").read_text()


def test_every_action_is_described_everywhere():
    import yaml

    registered = {
        svc.SERVICE_GENERATE_PAIRING_CODE, svc.SERVICE_GET_PAIRING_CODE,
        svc.SERVICE_ROTATE_PAIRING_CODE, svc.SERVICE_GET_LINKS, svc.SERVICE_REFRESH,
        svc.SERVICE_SET_OPTIONS, svc.SERVICE_PAIR, svc.SERVICE_ADD_CUSTOM_RELAY,
    }
    assert registered == set(ACTIONS)
    in_yaml = set(yaml.safe_load((PKG / "services.yaml").read_text()))
    strings = json.loads((PKG / "strings.json").read_text())
    icons = json.loads((PKG / "icons.json").read_text())
    assert registered == in_yaml == set(strings["services"]) == set(icons["services"])
    for name, body in yaml.safe_load((PKG / "services.yaml").read_text()).items():
        for field in (body or {}).get("fields", {}):
            assert field in strings["services"][name]["fields"], (name, field)


def test_every_flow_step_and_menu_option_has_text():
    """A step with no title renders blank in the dialog and fails silently."""
    s = json.loads((PKG / "strings.json").read_text())
    for flow, steps in (
        ("config", ["user", "pair", "generate", "manual", "links", "reauth_confirm"]),
        ("options", ["init", "settings", "links", "pairing_code", "pairing_unknown", "rotate_code"]),
    ):
        for step in steps:
            assert s[flow]["step"][step]["title"], (flow, step)
    assert set(s["config"]["step"]["user"]["menu_options"]) == {"pair", "generate", "manual", "links"}
    assert set(s["options"]["step"]["init"]["menu_options"]) == {"settings", "pairing_code", "links"}
    for step in ("pairing_code", "pairing_unknown"):
        assert set(s["options"]["step"][step]["menu_options"]) == {"init", "rotate_code"}
    # Every {placeholder} the descriptions use is one the flow actually supplies.
    for key in LINKS:
        assert "{" + key + "}" in s["config"]["step"]["links"]["description"]
    for ph in ("{code}", "{worker_url}", "{read_token}"):
        assert ph in s["options"]["step"]["pairing_code"]["description"]
    assert "{code}" in s["config"]["step"]["generate"]["description"]
    assert "{code}" in s["options"]["step"]["rotate_code"]["description"]
    for key in (
        "unknown_entry", "entry_not_loaded", "no_entries", "multiple_entries", "no_code_stored",
        "not_paired", "invalid_code", "invalid_url", "already_configured", "invalid_auth",
        "cannot_connect",
    ):
        assert s["exceptions"][key]["message"], key
    # An import flow ends with a reason, and a reason with no text shows as a bare key.
    for key in ("already_configured", "invalid_code", "invalid_url", "invalid_auth", "cannot_connect"):
        assert s["config"]["abort"][key], key
    for key in ("invalid_auth", "cannot_connect"):
        assert s["options"]["error"][key], key


def test_every_placeholder_in_the_strings_is_one_something_supplies():
    """A {name} nobody fills in renders as the literal braces."""
    import re

    s = json.loads((PKG / "strings.json").read_text())
    supplied = {
        ("config", "links"): set(LINKS), ("options", "links"): set(LINKS),
        ("config", "generate"): {"code"}, ("options", "rotate_code"): {"code"},
        ("options", "pairing_code"): {"code", "worker_url", "read_token"},
        ("options", "pairing_unknown"): {"worker_url", "read_token"},
    }
    for flow in ("config", "options"):
        for step, body in s[flow]["step"].items():
            used = set(re.findall(r"\{(\w+)\}", body.get("description", "")))
            assert used <= supplied.get((flow, step), set()), (flow, step, used)

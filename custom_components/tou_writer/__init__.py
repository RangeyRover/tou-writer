"""TOU Writer — MVP Home Assistant component for pushing TOU rates to Tesla via Teslemetry."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.components import persistent_notification

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tou_writer"
TESLEMETRY_API_BASE_URL = "https://api.teslemetry.com"
NOTIFICATION_ID = "tou_writer_push_failure"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # seconds — exponential backoff
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
PERMANENT_FAILURE_CODES = {400, 401, 403}


# ---------------------------------------------------------------------------
# Service schema
# ---------------------------------------------------------------------------

RATE_SCHEMA = vol.Schema(
    {
        vol.Required("start"): str,  # "HH:MM"
        vol.Required("end"): str,    # "HH:MM"
        vol.Required("buy"): vol.Coerce(float),   # c/kWh
        vol.Required("sell"): vol.Coerce(float),   # c/kWh
    }
)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("rates"): vol.All(
            list, vol.Length(min=1), [RATE_SCHEMA]
        ),
        vol.Optional("plan_name"): str,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_time_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight (0–1439).

    '00:00' as an *end* time means midnight = 1440 (handled by caller).
    """
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str!r} (expected HH:MM)")
    hours, mins = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and mins in (0, 30)):
        # Allow any minute value for input flexibility,
        # but warn if not on a 30-min boundary
        pass
    return hours * 60 + mins


DEFAULT_PLAN_NAME = "Custom TOU (TOU Writer)"


def _build_tariff(
    rates: list[dict[str, Any]],
    plan_name: str | None = None,
) -> dict[str, Any]:
    """Expand simple rate periods into a Tesla tariff_content_v2 structure.

    Args:
        rates: list of {start, end, buy, sell} dicts.
               buy/sell in cents/kWh.
        plan_name: optional display name for the rate plan in the Tesla app.

    Returns:
        Complete tariff_content_v2 dict ready for Tesla API.
    """
    # Build a minute-indexed lookup: minute -> (buy_dollars, sell_dollars)
    minute_prices: dict[int, tuple[float, float]] = {}

    for rate in rates:
        start_min = _parse_time_to_minutes(rate["start"])
        end_min = _parse_time_to_minutes(rate["end"])

        # Handle midnight wrap: end "00:00" means end of day
        if end_min == 0:
            end_min = 1440

        buy_dollars = round(rate["buy"] / 100.0, 6)
        sell_dollars = round(rate["sell"] / 100.0, 6)

        m = start_min
        while m < end_min:
            minute_prices[m] = (buy_dollars, sell_dollars)
            m += 30  # Tesla uses 30-min slots

    # Build the 48 PERIOD keys
    buy_prices: dict[str, float] = {}
    sell_prices: dict[str, float] = {}
    period_keys: list[str] = []

    for slot in range(48):
        minutes = slot * 30
        h = minutes // 60
        m = minutes % 60
        key = f"PERIOD_{h:02d}_{m:02d}"
        period_keys.append(key)

        if minutes in minute_prices:
            buy_dollars, sell_dollars = minute_prices[minutes]
        else:
            _LOGGER.warning("No rate covers period %s — defaulting to 0", key)
            buy_dollars, sell_dollars = 0.0, 0.0

        buy_prices[key] = buy_dollars
        sell_prices[key] = sell_dollars

    # Build TOU period definitions (each half-hour is its own period)
    tou_periods: dict[str, Any] = {}
    for i, key in enumerate(period_keys):
        slot_min = i * 30
        h = slot_min // 60
        m = slot_min % 60
        end_slot = slot_min + 30
        end_h = end_slot // 60
        end_m = end_slot % 60

        tou_periods[key] = {
            "name": key,
            "fromDayOfWeek": 0,
            "toDayOfWeek": 6,
            "fromHour": h,
            "fromMinute": m,
            "toHour": end_h if end_h < 24 else 0,
            "toMinute": end_m,
        }

    name = plan_name or DEFAULT_PLAN_NAME

    # Assemble tariff_content_v2
    tariff = {
        "version": 1,
        "code": "TOU_WRITER:CUSTOM",
        "name": name,
        "utility": "Custom",
        "currency": "AUD",
        "daily_charges": [{"name": "Charge"}],
        "demand_charges": {
            "ALL": {"rates": {"ALL": 0}},
            "Summer": {},
            "Winter": {},
        },
        "energy_charges": {
            "ALL": {"rates": {"ALL": 0}},
            "Summer": {"rates": buy_prices},
            "Winter": {},
        },
        "seasons": {
            "Summer": {
                "fromMonth": 1,
                "toMonth": 12,
                "fromDay": 1,
                "toDay": 31,
                "tou_periods": tou_periods,
            },
            "Winter": {
                "fromDay": 0,
                "toDay": 0,
                "fromMonth": 0,
                "toMonth": 0,
                "tou_periods": {},
            },
        },
        "sell_tariff": {
            "name": f"{name} (Sell)",
            "utility": "Custom",
            "daily_charges": [{"name": "Charge"}],
            "demand_charges": {
                "ALL": {"rates": {"ALL": 0}},
                "Summer": {},
                "Winter": {},
            },
            "energy_charges": {
                "ALL": {"rates": {"ALL": 0}},
                "Summer": {"rates": sell_prices},
                "Winter": {},
            },
            "seasons": {
                "Summer": {
                    "fromMonth": 1,
                    "toMonth": 12,
                    "fromDay": 1,
                    "toDay": 31,
                    "tou_periods": tou_periods,
                },
                "Winter": {
                    "fromDay": 0,
                    "toDay": 0,
                    "fromMonth": 0,
                    "toMonth": 0,
                    "tou_periods": {},
                },
            },
        },
    }

    return tariff


def _fire_event(
    hass: HomeAssistant,
    site_id: str,
    plan_name: str | None,
    success: bool,
    attempt_count: int,
    error: str | None = None,
) -> None:
    """Fire a tou_writer_push_result event for automations."""
    event_data: dict[str, Any] = {
        "success": success,
        "site_id": site_id[:4] + "***",
        "plan_name": plan_name or DEFAULT_PLAN_NAME,
        "attempt_count": attempt_count,
    }
    if error:
        event_data["error"] = error
    hass.bus.async_fire("tou_writer_push_result", event_data)


async def _send_to_teslemetry(
    session: aiohttp.ClientSession,
    site_id: str,
    token: str,
    tariff: dict[str, Any],
) -> tuple[bool, int]:
    """POST tariff to Tesla via Teslemetry API.

    Returns (success, http_status_code). Status is 0 on network error.
    """
    url = f"{TESLEMETRY_API_BASE_URL}/api/1/energy_sites/{site_id}/time_of_use_settings"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "tou_settings": {
            "tariff_content_v2": tariff,
        }
    }

    # Log payload summary
    buy_rates = tariff.get("energy_charges", {}).get("Summer", {}).get("rates", {})
    if buy_rates:
        values = list(buy_rates.values())
        _LOGGER.debug(
            "TOU payload: %d periods, buy $%.4f–$%.4f",
            len(values),
            min(values),
            max(values),
        )

    try:
        async with session.post(
            url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status == 200:
                result = await response.json()
                _LOGGER.info(
                    "TOU schedule pushed successfully (%d periods)",
                    len(buy_rates),
                )
                _LOGGER.debug("Teslemetry response: %s", result)
                return True, 200

            error_text = await response.text()
            _LOGGER.error(
                "Failed to push TOU schedule: HTTP %s — %s",
                response.status,
                error_text[:500],
            )
            return False, response.status

    except aiohttp.ClientError as err:
        _LOGGER.error("Network error pushing TOU schedule: %s", err)
        return False, 0
    except Exception as err:
        _LOGGER.error("Unexpected error pushing TOU schedule: %s", err)
        return False, 0


async def _send_with_retry(
    session: aiohttp.ClientSession,
    site_id: str,
    token: str,
    tariff: dict[str, Any],
) -> tuple[bool, int]:
    """Push tariff with exponential backoff retry on transient failures.

    Returns (success, attempt_count).
    """
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        success, status = await _send_to_teslemetry(session, site_id, token, tariff)

        if success:
            return True, attempt

        # Permanent failure — don't retry
        if status in PERMANENT_FAILURE_CODES:
            _LOGGER.error(
                "Permanent failure (HTTP %d) — not retrying", status
            )
            last_error = f"HTTP {status}"
            return False, attempt

        last_error = f"HTTP {status}" if status else "Network error"

        # Last attempt — don't sleep
        if attempt == MAX_RETRIES:
            break

        # Calculate delay
        if status == 429:
            # Respect Retry-After header if available (extracted from status)
            # Default to backoff delay
            delay = RETRY_DELAYS[attempt - 1]
            _LOGGER.warning(
                "Rate limited (429) — retrying in %ds (attempt %d/%d)",
                delay, attempt, MAX_RETRIES,
            )
        elif status in RETRIABLE_STATUS_CODES or status == 0:
            delay = RETRY_DELAYS[attempt - 1]
            _LOGGER.warning(
                "%s — retrying in %ds (attempt %d/%d)",
                last_error, delay, attempt, MAX_RETRIES,
            )
        else:
            # Unexpected status — don't retry
            return False, attempt

        await asyncio.sleep(delay)

    _LOGGER.error(
        "All %d retry attempts exhausted. Last error: %s",
        MAX_RETRIES, last_error,
    )
    return False, MAX_RETRIES


async def _verify_tariff(
    session: aiohttp.ClientSession,
    site_id: str,
    token: str,
    sent_tariff: dict[str, Any],
) -> bool:
    """GET site_info and compare tariff_content_v2 rates against what was sent.

    Returns True if rates match, False on mismatch or error.
    """
    url = f"{TESLEMETRY_API_BASE_URL}/api/1/energy_sites/{site_id}/site_info"
    headers = {
        "Authorization": f"Bearer {token}",
    }

    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                _LOGGER.warning(
                    "Readback verification failed — HTTP %d from site_info",
                    response.status,
                )
                return False

            data = await response.json()

    except (aiohttp.ClientError, Exception) as err:
        _LOGGER.warning("Readback verification error: %s", err)
        return False

    # Extract stored rates
    stored = (
        data.get("response", {})
        .get("tariff_content_v2", {})
        .get("energy_charges", {})
        .get("Summer", {})
        .get("rates", {})
    )
    sent = (
        sent_tariff
        .get("energy_charges", {})
        .get("Summer", {})
        .get("rates", {})
    )

    if not stored:
        _LOGGER.warning("Readback verification — no rates found in site_info")
        return False

    # Compare each period
    mismatches = []
    for period_key, sent_value in sent.items():
        stored_value = stored.get(period_key)
        if stored_value is None:
            mismatches.append(f"{period_key}: missing")
        elif abs(stored_value - sent_value) > 0.001:
            mismatches.append(
                f"{period_key}: sent={sent_value}, stored={stored_value}"
            )

    if mismatches:
        _LOGGER.warning(
            "Push returned 200 but verification failed — %d mismatches: %s",
            len(mismatches),
            ", ".join(mismatches[:5]),
        )
        return False

    _LOGGER.info("Readback verification passed — all %d rates match", len(sent))
    return True


# ---------------------------------------------------------------------------
# HA setup (config flow — no YAML editing needed)
# ---------------------------------------------------------------------------

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the TOU Writer component (YAML — no-op, config flow handles it)."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "ConfigEntry",
) -> bool:
    """Set up TOU Writer from a config entry (UI-based setup)."""
    # Store credentials from config entry for the service handler
    token = entry.data["teslemetry_token"]
    site_id = entry.data["site_id"]

    async def async_handle_push_tou(call: ServiceCall) -> None:
        """Handle the tou_writer.push_tou service call."""
        rates = call.data["rates"]
        plan_name = call.data.get("plan_name")

        _LOGGER.info(
            "Building TOU schedule from %d rate period(s) for site %s",
            len(rates),
            site_id[:4] + "***",
        )

        # Build tariff
        try:
            tariff = _build_tariff(rates, plan_name=plan_name)
        except Exception as err:
            _LOGGER.error("Failed to build tariff: %s", err)
            _fire_event(hass, site_id, plan_name, False, 0, str(err))
            return

        # Push with retry
        session = async_get_clientsession(hass)
        success, attempts = await _send_with_retry(session, site_id, token, tariff)

        if success:
            # Readback verification — wait for Tesla to propagate
            await asyncio.sleep(2)
            verified = await _verify_tariff(session, site_id, token, tariff)
            if not verified:
                _LOGGER.warning("TOU Writer: push succeeded but readback verification failed")

            # Dismiss any previous failure notification
            persistent_notification.async_dismiss(
                hass, notification_id=NOTIFICATION_ID
            )

            # Fire success event
            _fire_event(hass, site_id, plan_name, True, attempts)
            _LOGGER.info("TOU Writer: push complete (attempt %d)", attempts)
        else:
            # Create persistent notification for failure
            persistent_notification.async_create(
                hass,
                f"TOU Writer failed to push rate schedule after {attempts} attempt(s). "
                f"Check System → Logs for details.",
                title="TOU Writer Push Failed",
                notification_id=NOTIFICATION_ID,
            )

            # Fire failure event
            _fire_event(
                hass, site_id, plan_name, False, attempts,
                f"Failed after {attempts} attempts",
            )
            _LOGGER.error("TOU Writer: push failed after %d attempt(s)", attempts)

    # Only register the service once (guard against reload)
    if not hass.services.has_service(DOMAIN, "push_tou"):
        hass.services.async_register(
            DOMAIN,
            "push_tou",
            async_handle_push_tou,
            schema=SERVICE_SCHEMA,
        )

    _LOGGER.info("TOU Writer loaded — service tou_writer.push_tou registered")
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: "ConfigEntry",
) -> bool:
    """Unload TOU Writer config entry."""
    hass.services.async_remove(DOMAIN, "push_tou")
    _LOGGER.info("TOU Writer unloaded")
    return True


"""Config flow for TOU Writer — collects Teslemetry token and site ID."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

DOMAIN = "tou_writer"


class TouWriterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TOU Writer."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the setup step — collect Teslemetry token and site ID."""
        errors = {}

        if user_input is not None:
            token = user_input.get("teslemetry_token", "").strip()
            site_id = user_input.get("site_id", "").strip()

            # Basic validation
            if not token:
                errors["teslemetry_token"] = "token_required"
            if not site_id:
                errors["site_id"] = "site_id_required"

            if not errors:
                # Prevent duplicate entries for the same site
                await self.async_set_unique_id(f"tou_writer_{site_id}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"TOU Writer (site {site_id[:4]}…)",
                    data={
                        "teslemetry_token": token,
                        "site_id": site_id,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("teslemetry_token"): str,
                    vol.Required("site_id"): str,
                }
            ),
            errors=errors,
        )

# TOU Writer for Home Assistant
**TOU Writer** allows you to push custom Time-of-Use (TOU) rate schedules to your Tesla Powerwall via the [Teslemetry](https://teslemetry.com) integration. This enables advanced control strategies, such as forcing your Powerwall to charge or discharge based on dynamic pricing (e.g., Amber Electric).
## Features
- **Dynamic TOU Pushes:** Send any list of rate periods to your Powerwall.
- **Robustness:** Includes retry logic, rate limit handling, and readback verification to ensure schedules are applied.
- **Observability:** Fires HA events (`tou_writer_push_result`) and creates persistent notifications on failure.
- **Safety:** Explicit timeouts and validation to prevent bad data.
## Installation
### Method 1: HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS > Integrations > Top right menu > Custom repositories**.
3. Add `https://github.com/RangeyRover/tou-writer` with category **Integration**.
4. Click **Download**.
5. Restart Home Assistant.
### Method 2: Manual
1. Copy the `custom_components/tou_writer` folder to your HA `config/custom_components/` directory.
2. Restart Home Assistant.
## Configuration
1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **TOU Writer**.
3. Follow the prompts. You will need to provide your **Teslemetry Access Token** and **Site ID**.
## Usage
### Service: `tou_writer.push_tou`
Pushes a TOU schedule to your Powerwall.
**Parameters:**
- `plan_name` (Optional): The name of the rate plan to display in the Tesla app (e.g., "Amber Smart TOU").
- `rates` (Required): A list of rate periods.
**Rate Period Object:**
- `start`: Start time (HH:MM)
- `end`: End time (HH:MM)
- `buy`: Buy price in cents/kWh
- `sell`: Sell price in cents/kWh
### Example: Amber Electric Automation
A common use case is syncing Amber Electric's dynamic 30-minute forecasts to the Powerwall to automate charging/discharging.
The provided automation example:
1. Reads Amber's 5-minute forecasts.
2. Aggregates them into 30-minute TOU slots.
3. Implements a **Rolling 24h Schedule** (past slots fill with tomorrow's data).
4. Pushes to Tesla **only when rates change** to avoid API spam (requires [MQTT](https://www.home-assistant.io/integrations/mqtt/) for state tracking).
**[View the Amber Automation YAML here](automations/amber_tesla.yaml)**
To use it:
1. Copy the YAML from `automations/amber_tesla.yaml`.
2. Create a new Automation in Home Assistant and paste the YAML (Edit in YAML mode).
3. Ensure you have the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) set up (used for deduping).
4. Run the automation manually once to initialize.
## Credits
- Built for [Home Assistant](https://www.home-assistant.io/)
- Uses [Teslemetry](https://teslemetry.com)

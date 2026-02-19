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

### Example: Amber Electric Automation (with Force Discharge)

Syncs Amber pricing to Powerwall and supports **Force Discharge** (exporting even when SOC is low) by manipulating prices.

**Features:**
- **Smart Sync:** Aggregates 5-min prices to 30-min TOU slots.
- **Force Discharge:** Use an input select to force the battery to dump energy (by boosting sell price +100c/kWh for the next hour).
- **Instant Response:** Updates immediately when you change modes.

**Setup in Home Assistant:**

1.  **Create a Helper:**
    - Go to **Settings > Devices & Services > Helpers > Create Helper > Dropdown**.
    - Name: `Powerwall Mode`
    - Entity ID: `input_select.powerwall_mode` (Important!)
    - Options:
        - `Normal`
        - `Discharge Start`
        - `Charge Start`
2.  **Create the Automation:**
    - Copy the YAML from [`amber_tesla_automation.yaml`](amber_tesla_automation.yaml) in this repo.
    - Create a new Automation in HA, switch to YAML mode, and paste it.
    - Ensure you have a working MQTT broker (for state deduplication).
3.  **Use it:**
    - Switch the `Powerwall Mode` dropdown on your dashboard to `Discharge Start` to force export for the next hour.
    - Switch back to `Normal` to resume standard optimization.
## Credits
- Built for [Home Assistant](https://www.home-assistant.io/)
- Uses [Teslemetry](https://teslemetry.com)

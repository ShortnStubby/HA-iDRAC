# Home Assistant iDRAC Controller Add-on

**<font color="red">⚠️ DEVELOPMENT VERSION - USE WITH CAUTION! ⚠️</font>**

**This is a work-in-progress, development version of the HA iDRAC Controller add-on. It is intended for testing and feedback. Unexpected behavior, bugs, or incomplete features are likely. Use this version at your own risk, especially when enabling fan control features, as incorrect configuration or software errors could potentially lead to server overheating if not carefully monitored.**

**For the stable version (if available), please refer to the main add-on list or a different repository/branch as indicated by the developer.**

---
**Next Roadmap Goal: Multi-Server Support. This is as yet NOT working**

**Control your Dell PowerEdge server's fan speeds based on CPU temperature and monitor key server metrics directly from Home Assistant.**

This add-on connects to your server's iDRAC interface using IPMI to:
* Read temperatures (CPU, Inlet, Exhaust).
* Read actual fan speeds (RPM).
* Read power consumption (Watts).
* Control fan speeds based on configurable temperature thresholds.
* Publish all data to MQTT for integration with Home Assistant, creating sensors automatically via MQTT Discovery.
* Provide a Web UI (via Ingress) for status overview and advanced configuration (like a multi-point fan curve, though primary logic uses simpler thresholds from HA config for now).

## Features

* **Dynamic Fan Control:** Adjusts fan speeds based on the hottest CPU core temperature using a 3-tier threshold system (Base, High, Critical).
* **Server Monitoring:** Creates Home Assistant sensors for:
    * Individual CPU Temperatures
    * Hottest CPU Temperature
    * Inlet Temperature
    * Exhaust Temperature
    * Individual Fan Speeds (RPM)
    * Power Consumption (Watts)
    * Target Fan Speed Percentage
    * Add-on Connectivity Status
* **MQTT Auto-Discovery:** Automatically creates and configures entities in Home Assistant.
* **Web UI via Ingress:**
    * View live server status (temperatures, fan speeds, power).
    * View current fan control settings.
    * (Future/Optional) Configure an advanced multi-point fan curve.
* **Configurable:** Set iDRAC credentials, fan thresholds, temperature units, and MQTT details via the Home Assistant add-on configuration panel.

## <font color="orange">⚠️ Important Note for Testers ⚠️</font>
* This version is for testing and development. Please report any issues or bugs encountered.
* **Monitor your server's temperatures and fan operation closely after enabling fan control.**
* The developer (Aesgarth) is not responsible for any damage or issues arising from the use of this development software.

## Prerequisites

1.  **Dell PowerEdge Server with iDRAC:** This add-on uses IPMI, which is available on most Dell PowerEdge servers with an iDRAC (iDRAC 7, 8, 9 and newer should generally work). This add-on has been tested with an R720 (iDRAC7).
2.  **Network Connectivity:** Your Home Assistant instance must be able to reach your server's iDRAC IP address over the network.
3.  **IPMI over LAN Enabled in iDRAC:** This is crucial.

    **How to Enable IPMI over LAN in iDRAC (General Steps):**

    The exact steps can vary slightly depending on your iDRAC version (iDRAC7, iDRAC8, iDRAC9, etc.).

    * **Access iDRAC Web Interface:** Open a web browser and navigate to your iDRAC's IP address. Log in with your iDRAC credentials.
    * **Navigate to Network Settings:**
        * **iDRAC 7/8:** Look for "iDRAC Settings" -> "Network" or "Connectivity".
        * **iDRAC 9:** Look for "iDRAC Settings" -> "Connectivity" -> "Network Settings".
    * **Find IPMI Settings:** Within the network settings, look for a section specifically labeled "IPMI Settings" or "IPMI over LAN."
        * Common path: (iDRAC Settings -> Network -> IPMI Settings link at the top or bottom of the page).
    * **Enable IPMI over LAN:**
        * There will be a checkbox or toggle: "Enable IPMI Over LAN". Ensure this is **checked/enabled**.
        * **Channel Privilege Level Limit:** Set this to "ADMINISTRATOR" or "OPERATOR" to allow fan control and sensor reading. Administrator is usually required for control.
        * **Encryption Key:** Leave as `0000000000000000000000000000000000000000` (40 zeros) unless you have specific IPMI 2.0 encryption needs (this add-on uses standard IPMItool commands that work with this default).
    * **Apply Settings:** Save and apply the changes. The iDRAC might restart its network interface.

    *If you cannot find these settings, consult your specific Dell PowerEdge server's iDRAC manual for "IPMI over LAN" configuration.*

4.  **MQTT Broker:** You need an MQTT broker accessible by Home Assistant. The `core-mosquitto` Home Assistant add-on is recommended.

## Installation (for this Development Version)

1.  **Add the Repository to Home Assistant:**
    * In Home Assistant, go to **Settings > Add-ons**.
    * Click the **"ADD-ON STORE"** button (usually bottom right).
    * Click the **three-dots menu** (⋮) in the top right corner and select **"Repositories"**.
    * In the "Manage add-on repositories" dialog, paste the following URL:
        ```
        [https://github.com/Aesgarth/HA-iDRAC](https://github.com/Aesgarth/HA-iDRAC)
        ```
       
    * Click **"ADD"** and then **"CLOSE"**.

2.  **Install the Add-on:**
    * Refresh your browser page if needed.
    * You should see **two versions** if you followed the multi-version setup: "HA iDRAC Controller" (stable) and "HA iDRAC Controller (Dev)".
    * For this development version, click on **"HA iDRAC Controller (Dev)"** (or the name you chose for your development version in its `config.yaml`).
    * Click **"INSTALL"**. This will download and build the add-on, which may take a few minutes.

## Configuration

After installation, you **must** configure the add-on before starting it.

1.  Go to the add-on page (Settings > Add-ons > "HA iDRAC Controller (Dev)").
2.  Switch to the **"Configuration"** tab.
3.  Fill in the options as described (iDRAC IP, username, password, fan thresholds, MQTT, etc.).
4.  Click **"SAVE"**.
5.  Go to the **"Info"** tab and click **"START"**.

## Web UI (Ingress Panel)

Once the add-on is started, you can access its web UI:
* Click on "iDRAC Control (Dev)" (or similar, based on the `name` in the dev `config.yaml`) in your Home Assistant sidebar.
* Or, go to the add-on's "Info" tab and click "OPEN WEB UI".

The Web UI currently provides:
* A status overview showing live temperatures, fan RPMs, power consumption, and the current target fan speed.
* Displays the "Simple Fan Mode" settings currently active from your HA add-on configuration.
* A link to a settings page for an "Advanced Fan Curve" (note: the main control logic currently uses the "Simple Fan Mode" settings from the HA configuration tab; the advanced curve is for future use or if you modify the Python script to prioritize it).

## Sensors Created in Home Assistant (via MQTT)

If MQTT is configured correctly, the following entities will be automatically discovered and created under a device representing your iDRAC:

* **Connectivity:**
    * `binary_sensor.idrac_controller_connectivity`: `online`/`offline` status of the add-on.
* **Temperatures (°C):**
    * `sensor.idrac_cpu_0_temperature` (and `_1`, `_2`, `_3` etc., based on detected CPUs)
    * `sensor.idrac_hottest_cpu_temp`
    * `sensor.idrac_inlet_temperature`
    * `sensor.idrac_exhaust_temperature`
* **Fans:**
    * `sensor.idrac_target_fan_speed`: Current target fan speed percentage (or "Auto").
    * `sensor.idrac_fan_X_rpm`: Actual speed for each detected fan (e.g., `sensor.idrac_fan_fan1a_tach_rpm`).
* **Power:**
    * `sensor.idrac_power_consumption`: Current server power usage in Watts.

*(Sensor entity IDs might vary slightly based on your iDRAC IP and sensor names).*

## Troubleshooting

* **Check the Add-on Log:** The first place to look for errors is the "Log" tab of the add-on in Home Assistant. Set "Log Level" to `debug` or `trace` in the Configuration for more detail.
* **IPMI Communication Errors:**
    * Verify "IPMI over LAN" is enabled in iDRAC.
    * Confirm iDRAC IP, username, and password.
    * Ensure UDP port 623 isn't blocked.
* **MQTT "Not Authorized" Errors:**
    * Check MQTT username/password match your broker's configuration.
* **Incorrect Sensor Data:** Regex patterns for parsing `ipmitool` output might need adjustment for your server model.

## Contributing / Reporting Issues

This is a development version. Please report any bugs, issues, or feature suggestions by opening an issue on the [GitHub repository](https://github.com/Aesgarth/HA-iDRAC/issues). Please provide logs and details about your server model if you encounter problems.

## License

This project uses the [MIT License](LICENSE).

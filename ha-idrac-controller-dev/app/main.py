# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys
import signal
import threading
import re
import json # Added json import

from . import ipmi_manager
from . import web_server
from . import mqtt_client

# --- Global Variables ---
running = True
addon_options = {} # Will store global defaults from HA options and current server context for the loop
servers_configs_list = [] # To store configs for all loaded servers
master_encryption_key = None # Store the master key from add-on config

server_info = { # This will need to become per-server later
    "manufacturer": "Unknown", "model": "Unknown", "is_gen14_plus": False,
    "cpu_generic_temp_pattern": None,
    "inlet_temp_name_pattern": None,
    "exhaust_temp_name_pattern": None
}
app_config = {} # For web_server's advanced fan curve settings
loop_count = 0
current_parsed_status = { # For sharing with web_server via file - will need to be multi-server later
    "cpu_temps_c": [], "hottest_cpu_temp_c": "N/A",
    "inlet_temp_c": "N/A", "exhaust_temp_c": "N/A",
    "target_fan_speed_percent": "N/A", "actual_fan_rpms": [],
    "power_consumption_watts": "N/A", # Added
    "last_updated": "Never"
}
STATUS_FILE = "/data/current_status.json" # This will need to be adapted for multi-server UI
SERVERS_CONFIG_FILE = "/data/servers_config.json" # Path to the new server configurations file

# MQTT Discovery Tracking (will need to become per-server)
discovered_cpu_sensors = set()
discovered_fan_rpm_sensors = set()
# static_sensors_discovered = False # Managed by mqtt_client on_connect

# --- Graceful Shutdown & Helpers ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

def determine_server_generation(model_name):
    if not model_name: return False
    match = re.search(r"^[RT]\s?(\d)(\d)\d+", model_name.upper())
    if match:
        try:
            gen_indicator_digit = int(match.group(2))
            if gen_indicator_digit >= 4: return True
        except (IndexError, ValueError): pass
    return False

def celsius_to_fahrenheit(celsius):
    if celsius is None: return None
    return round((celsius * 9/5) + 32, 1)

def fahrenheit_to_celsius(fahrenheit):
    if fahrenheit is None: return None
    return round((fahrenheit - 32) * 5/9, 1)

def save_current_status_to_file(status_dict): # Will need to save multi-server status later
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(status_dict, f, indent=4)
    except (IOError, PermissionError) as e:
        print(f"[ERROR] Could not save status to {STATUS_FILE}: {e}", flush=True)

# --- Stub for Password Decryption ---
def decrypt_password_stub(encrypted_pass_placeholder, key_used):
    # In a real scenario, you'd use a cryptography library here.
    if not key_used:
        print("[WARN] Master encryption key is not set. Password decryption cannot be performed securely (stub returning as is).")
    # For this stub, we assume the "encrypted_pass_placeholder" is the actual password.
    # print(f"[STUB] 'Decrypting' password. Placeholder: '{encrypted_pass_placeholder}'")
    return encrypted_pass_placeholder

# --- Main Application Logic ---
def load_and_configure(mqtt_handler):
    global addon_options, servers_configs_list, master_encryption_key, app_config, server_info
    print("[MAIN] Loading configuration and initializing...", flush=True)

    # Load global HA add-on options
    master_encryption_key = os.getenv("MASTER_ENCRYPTION_KEY")
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    addon_options = { # These are now primarily global defaults
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),
        "log_level": log_level,
        "temperature_unit": os.getenv("TEMPERATURE_UNIT", "C").upper(),
        "base_fan_speed_percent": int(os.getenv("BASE_FAN_SPEED_PERCENT", "20")),
        "low_temp_threshold": int(os.getenv("LOW_TEMP_THRESHOLD", "45")),
        "high_temp_fan_speed_percent": int(os.getenv("HIGH_TEMP_FAN_SPEED_PERCENT", "50")),
        "critical_temp_threshold": int(os.getenv("CRITICAL_TEMP_THRESHOLD", "65")),
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "mqtt_port": int(os.getenv("MQTT_PORT", "1883")),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", "")
        # This will also hold 'current_server_config_for_loop' temporarily
    }
    print(f"[{log_level.upper()}] Global add-on options loaded. LogLevel={log_level}", flush=True)
    if not master_encryption_key:
        print("[WARN] MASTER_ENCRYPTION_KEY is not set in add-on configuration. Passwords in servers_config.json will be handled as plain text by the stub decryption.", flush=True)

    # Load server configurations from the JSON file
    if os.path.exists(SERVERS_CONFIG_FILE):
        try:
            with open(SERVERS_CONFIG_FILE, 'r') as f:
                raw_servers_list = json.load(f)
                for server_conf_raw in raw_servers_list:
                    if not server_conf_raw.get("enabled", False):
                        print(f"[INFO] Server '{server_conf_raw.get('alias', 'Unknown')}' is disabled, skipping.", flush=True)
                        continue

                    decrypted_password = decrypt_password_stub(
                        server_conf_raw.get("idrac_encrypted_password", server_conf_raw.get("idrac_password", "")), # Fallback for plain text during transition
                        master_encryption_key
                    )
                    
                    final_server_config = {
                        "alias": server_conf_raw.get("alias", f"idrac-{server_conf_raw.get('idrac_ip', 'unknown_ip')}"),
                        "idrac_ip": server_conf_raw.get("idrac_ip"),
                        "idrac_username": server_conf_raw.get("idrac_username"),
                        "idrac_password": decrypted_password,
                        "temperature_unit": server_conf_raw.get("temperature_unit", addon_options["temperature_unit"]),
                        "base_fan_speed_percent": int(server_conf_raw.get("base_fan_speed_percent", addon_options["base_fan_speed_percent"])),
                        "low_temp_threshold": int(server_conf_raw.get("low_temp_threshold", addon_options["low_temp_threshold"])),
                        "high_temp_fan_speed_percent": int(server_conf_raw.get("high_temp_fan_speed_percent", addon_options["high_temp_fan_speed_percent"])),
                        "critical_temp_threshold": int(server_conf_raw.get("critical_temp_threshold", addon_options["critical_temp_threshold"])),
                    }
                    
                    if not final_server_config["idrac_ip"] or not final_server_config["idrac_username"] or not final_server_config["idrac_password"]: # Password can be empty if intended
                        print(f"[ERROR] Server '{final_server_config['alias']}' is missing critical info (IP or Username). Skipping.", flush=True)
                        continue
                        
                    servers_configs_list.append(final_server_config)
        except json.JSONDecodeError:
            print(f"[ERROR] Could not decode {SERVERS_CONFIG_FILE}. Please check its format.", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to load or process {SERVERS_CONFIG_FILE}: {e}", flush=True)
    else:
        print(f"[WARN] {SERVERS_CONFIG_FILE} not found. No servers to manage.", flush=True)

    if not servers_configs_list:
        print("[ERROR] No valid server configurations loaded. Cannot continue.", flush=True)
        sys.exit(1) # Exit if no servers are configured, as the rest of the logic depends on it

    # --- TEMPORARY: For Step 1, configure IPMI and MQTT for the FIRST enabled server ---
    first_server_for_testing = None
    for s_conf in servers_configs_list: # Find first enabled server
        if s_conf.get("idrac_ip"): # Basic check
             first_server_for_testing = s_conf
             break
    
    if not first_server_for_testing:
        print("[ERROR] No enabled server found in the configuration list. Cannot continue.", flush=True)
        sys.exit(1)

    print(f"[{log_level.upper()}] Initializing for first server (for testing): {first_server_for_testing['alias']} ({first_server_for_testing['idrac_ip']})", flush=True)

    ipmi_manager.configure_ipmi( # This will be replaced by IPMIManager class instance per thread
        first_server_for_testing["idrac_ip"],
        first_server_for_testing["idrac_username"],
        first_server_for_testing["idrac_password"],
        log_level=log_level
    )

    model_data = ipmi_manager.get_server_model_info() # Uses the globally configured IPMI target
    if model_data and model_data.get("model") != "Unknown":
        server_info.update(model_data) # server_info will become per-server state
        server_info["is_gen14_plus"] = determine_server_generation(server_info["model"])
        print(f"[{log_level.upper()}] Server: {server_info['manufacturer']} {server_info['model']} (Gen14+: {server_info['is_gen14_plus']}) for {first_server_for_testing['alias']}", flush=True)
    else:
        print(f"[WARNING] Could not determine server model for {first_server_for_testing['alias']}.", flush=True)
    
    if mqtt_handler: # Configure MQTT client with device info for the first server
        mqtt_handler.configure_broker( # Global MQTT broker settings
            addon_options["mqtt_host"], addon_options["mqtt_port"],
            addon_options["mqtt_username"], addon_options["mqtt_password"],
            log_level
        )
        # Device info will be specific to this first server for now
        mqtt_handler.set_device_info(
            server_info.get("manufacturer"),
            server_info.get("model"),
            first_server_for_testing.get("idrac_ip") # Use this server's IP for MQTT device ID
        )

    server_info["cpu_generic_temp_pattern"] = r"^Temp$" # These patterns might become configurable per server type later
    server_info["inlet_temp_name_pattern"] = r"Inlet Temp"
    server_info["exhaust_temp_name_pattern"] = r"Exhaust Temp"
    # print(f"[{log_level.upper()}] Using temp patterns: CPU_generic='{server_info['cpu_generic_temp_pattern']}', Inlet='{server_info['inlet_temp_name_pattern']}', Exhaust='{server_info['exhaust_temp_name_pattern']}'", flush=True)

    # Prepare specific config for the main_control_loop (for this first server)
    current_loop_server_config = first_server_for_testing.copy() # Use a copy
    temp_unit = current_loop_server_config["temperature_unit"]
    
    # Ensure all necessary keys for fan control are present, falling back to global defaults
    current_loop_server_config["base_fan_speed_percent"] = int(current_loop_server_config.get("base_fan_speed_percent", addon_options["base_fan_speed_percent"]))
    current_loop_server_config["low_temp_threshold"] = int(current_loop_server_config.get("low_temp_threshold", addon_options["low_temp_threshold"]))
    current_loop_server_config["high_temp_fan_speed_percent"] = int(current_loop_server_config.get("high_temp_fan_speed_percent", addon_options["high_temp_fan_speed_percent"]))
    current_loop_server_config["critical_temp_threshold"] = int(current_loop_server_config.get("critical_temp_threshold", addon_options["critical_temp_threshold"]))

    if temp_unit == "F":
        current_loop_server_config["low_temp_threshold_c"] = fahrenheit_to_celsius(current_loop_server_config["low_temp_threshold"])
        current_loop_server_config["critical_temp_threshold_c"] = fahrenheit_to_celsius(current_loop_server_config["critical_temp_threshold"])
    else: # Already Celsius or unknown, treat as Celsius
        current_loop_server_config["low_temp_threshold_c"] = float(current_loop_server_config["low_temp_threshold"])
        current_loop_server_config["critical_temp_threshold_c"] = float(current_loop_server_config["critical_temp_threshold"])
    
    addon_options["current_server_config_for_loop"] = current_loop_server_config # Store it for main_control_loop
    print(f"[{log_level.upper()}] Effective thresholds for {current_loop_server_config['alias']} (in C for logic): Low={current_loop_server_config['low_temp_threshold_c']:.1f}C, Crit={current_loop_server_config['critical_temp_threshold_c']:.1f}C", flush=True)
    
    app_config = web_server.load_app_config() # This is for the web UI's own advanced fan curve settings file
    print(f"[{log_level.upper()}] Loaded app_config (web server's advanced fan curve): {app_config}", flush=True)


def main_control_loop(mqtt_handler):
    global running, app_config, addon_options, server_info, loop_count, current_parsed_status # server_info is still global here
    global discovered_cpu_sensors, discovered_fan_rpm_sensors

    # For Step 1, we rely on load_and_configure to set up IPMI for one server
    # and place its specific operational config into addon_options["current_server_config_for_loop"]
    current_server_op_config = addon_options.get("current_server_config_for_loop")
    if not current_server_op_config:
        print("[ERROR] Current server operational config not found in main_control_loop. Exiting.", flush=True)
        return
    
    log_level = addon_options['log_level'] # Global log level
    server_alias = current_server_op_config['alias']

    # IPMI credentials for this server were already configured globally in load_and_configure for Step 1
    # In future, IPMIManager instance will be passed or created here per thread.
    print(f"[{log_level.upper()}] Entering main control loop for server: {server_alias}. Interval: {addon_options['check_interval_seconds']}s", flush=True)

    while running:
        start_time = time.time()
        sleep_duration = float(addon_options["check_interval_seconds"])

        try:
            print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} for {server_alias} Start ---", flush=True)

            if loop_count > 0 and loop_count % 10 == 0: # Reload app_config (web server settings) periodically
                print(f"[{log_level.upper()}] Reloading app config (web server's advanced curve) from /data/app_config.json", flush=True)
                app_config = web_server.load_app_config()

            # --- Retrieve and Parse Temperatures --- (Using globally configured ipmi_manager for now)
            raw_temp_sdr_data = ipmi_manager.retrieve_temperatures_raw()
            parsed_temperatures_c = {"cpu_temps": [], "inlet_temp": None, "exhaust_temp": None}
            if raw_temp_sdr_data:
                # server_info patterns are still global for now
                parsed_temperatures_c = ipmi_manager.parse_temperatures(
                    raw_temp_sdr_data, server_info["cpu_generic_temp_pattern"],
                    server_info["inlet_temp_name_pattern"], server_info["exhaust_temp_name_pattern"]
                )
            # print(f"[{log_level.upper()}] Parsed Temperatures (C) for {server_alias}: {parsed_temperatures_c}", flush=True)


            # --- Retrieve and Parse Fan RPMs ---
            raw_fan_sdr_data = ipmi_manager.retrieve_fan_rpms_raw()
            parsed_fan_rpms = []
            if raw_fan_sdr_data:
                parsed_fan_rpms = ipmi_manager.parse_fan_rpms(raw_fan_sdr_data)
            # print(f"[{log_level.upper()}] Parsed Fan RPMs for {server_alias}: {parsed_fan_rpms}", flush=True)

            # --- Retrieve and Parse Power Consumption ---
            raw_power_sdr_data = ipmi_manager.retrieve_power_sdr_raw()
            power_consumption_watts = None
            if raw_power_sdr_data:
                power_consumption_watts = ipmi_manager.parse_power_consumption(raw_power_sdr_data)
            # print(f"[{log_level.upper()}] Parsed Power Consumption for {server_alias}: {power_consumption_watts}W", flush=True)

            # --- Dynamic MQTT Discovery (CPUs and Fans) ---
            # This will need to be per-server, using server_alias in unique_id and topics
            if mqtt_handler and mqtt_handler.is_connected:
                cpu_temps_list_c_current_cycle = parsed_temperatures_c.get("cpu_temps", [])
                # For Step 1, discovered_cpu_sensors is global. This will create entities for the first server.
                if len(discovered_cpu_sensors) != len(cpu_temps_list_c_current_cycle) or not discovered_cpu_sensors:
                    new_cpu_slugs = set()
                    for i in range(len(cpu_temps_list_c_current_cycle)):
                        # TODO: Incorporate server_alias into slug for multi-server
                        slug = f"cpu_{i}_temp"
                        mqtt_handler.publish_sensor_discovery(
                            sensor_type_slug=slug, sensor_name=f"CPU {i} Temperature", # TODO: Add server_alias to name
                            device_class="temperature", unit_of_measurement="°C",
                            value_template="{{ value_json.temperature | round(1) }}"
                        )
                        new_cpu_slugs.add(slug)
                    discovered_cpu_sensors = new_cpu_slugs
                
                for i, fan_info in enumerate(parsed_fan_rpms):
                    fan_name = fan_info["name"]
                    safe_fan_name_slug = re.sub(r'[^a-zA-Z0-9_]+', '_', fan_name).lower().strip('_')
                    if not safe_fan_name_slug: safe_fan_name_slug = f"fan_{i}"
                    # TODO: Incorporate server_alias into slug
                    rpm_sensor_slug = f"fan_{safe_fan_name_slug}_rpm"
                    if rpm_sensor_slug not in discovered_fan_rpm_sensors:
                        mqtt_handler.publish_sensor_discovery(
                            sensor_type_slug=rpm_sensor_slug, sensor_name=f"{fan_name} RPM", # TODO: Add server_alias
                            unit_of_measurement="RPM", icon="mdi:fan",
                            value_template="{{ value_json.rpm | round(0) }}"
                        )
                        discovered_fan_rpm_sensors.add(rpm_sensor_slug)

            # --- Determine Hottest CPU ---
            hottest_cpu_temp_c = None
            cpu_temps_list_c = parsed_temperatures_c.get("cpu_temps", [])
            if cpu_temps_list_c:
                hottest_cpu_temp_c = max(cpu_temps_list_c)
            # print(f"[{log_level.upper()}] Hottest CPU Temp for {server_alias}: {hottest_cpu_temp_c}°C", flush=True)


            # --- Fan Control Logic ---
            target_fan_speed_display = "N/A"
            if hottest_cpu_temp_c is not None:
                # Use thresholds from the specific server's operational config
                low_thresh_c = current_server_op_config["low_temp_threshold_c"]
                crit_thresh_c = current_server_op_config["critical_temp_threshold_c"]
                base_fan_val = current_server_op_config["base_fan_speed_percent"]
                high_fan_val = current_server_op_config["high_temp_fan_speed_percent"]

                if hottest_cpu_temp_c >= crit_thresh_c:
                    print(f"[{log_level.upper()}] {server_alias} CPU ({hottest_cpu_temp_c}°C) >= CRITICAL ({crit_thresh_c}°C). Dell auto.", flush=True)
                    ipmi_manager.apply_dell_fan_control_profile()
                    target_fan_speed_display = "Dell Auto"
                elif hottest_cpu_temp_c >= low_thresh_c:
                    target_fan_speed_val = high_fan_val
                    print(f"[{log_level.upper()}] {server_alias} CPU ({hottest_cpu_temp_c}°C) >= LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                    ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                    target_fan_speed_display = target_fan_speed_val
                else:
                    target_fan_speed_val = base_fan_val
                    print(f"[{log_level.upper()}] {server_alias} CPU ({hottest_cpu_temp_c}°C) < LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                    ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                    target_fan_speed_display = target_fan_speed_val
            else:
                print(f"[WARNING] {server_alias} Hottest CPU temp N/A. Applying Dell auto fans for safety.", flush=True)
                ipmi_manager.apply_dell_fan_control_profile()
                target_fan_speed_display = "Dell Auto (Safety)"
            
            # --- Update Shared Status File for Web UI ---
            # For Step 1, this current_parsed_status is still for the single (first) server
            current_parsed_status_for_file = { # This structure will represent ONE server. Later it will be a dict of these.
                "alias": server_alias, # Added alias
                "cpu_temps_c": cpu_temps_list_c,
                "hottest_cpu_temp_c": hottest_cpu_temp_c,
                "inlet_temp_c": parsed_temperatures_c.get("inlet_temp"),
                "exhaust_temp_c": parsed_temperatures_c.get("exhaust_temp"),
                "target_fan_speed_percent": target_fan_speed_display,
                "actual_fan_rpms": parsed_fan_rpms,
                "power_consumption_watts": power_consumption_watts,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S %Z")
            }
            save_current_status_to_file(current_parsed_status_for_file) # Web UI will need to adapt to this structure if it changes for multi-server

            # --- MQTT State Publishing ---
            # For Step 1, states are published for the first server. Topics are not yet server-specific.
            if mqtt_handler and mqtt_handler.is_connected:
                for i, cpu_temp_val in enumerate(cpu_temps_list_c):
                    mqtt_handler.publish_sensor_state(sensor_type_slug=f"cpu_{i}_temp", value_dict={"temperature": cpu_temp_val})
                if parsed_temperatures_c.get("inlet_temp") is not None:
                     mqtt_handler.publish_sensor_state(sensor_type_slug="inlet_temp", value_dict={"temperature": parsed_temperatures_c["inlet_temp"]})
                if parsed_temperatures_c.get("exhaust_temp") is not None:
                     mqtt_handler.publish_sensor_state(sensor_type_slug="exhaust_temp", value_dict={"temperature": parsed_temperatures_c["exhaust_temp"]})
                if hottest_cpu_temp_c is not None:
                    mqtt_handler.publish_sensor_state(sensor_type_slug="hottest_cpu_temp", value_dict={"temperature": hottest_cpu_temp_c})
                
                # Target Fan Speed
                target_speed_mqtt_val = None
                if isinstance(target_fan_speed_display, (int, float)):
                    target_speed_mqtt_val = int(target_fan_speed_display)
                elif isinstance(target_fan_speed_display, str) and target_fan_speed_display.isdigit():
                    target_speed_mqtt_val = int(target_fan_speed_display)
                # If it's "Dell Auto" or similar, target_speed_mqtt_val remains None (or you can publish the string)
                mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": target_speed_mqtt_val})
                
                if power_consumption_watts is not None:
                    mqtt_handler.publish_sensor_state(sensor_type_slug="power_consumption", value_dict={"power": power_consumption_watts})
                for i, fan_info in enumerate(parsed_fan_rpms):
                    fan_name = fan_info["name"]
                    safe_fan_name_slug = re.sub(r'[^a-zA-Z0-9_]+', '_', fan_name).lower().strip('_')
                    if not safe_fan_name_slug: safe_fan_name_slug = f"fan_{i}"
                    mqtt_handler.publish_sensor_state(sensor_type_slug=f"fan_{safe_fan_name_slug}_rpm", value_dict={"rpm": fan_info["rpm"]})

            print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} for {server_alias} End ---", flush=True)
        
        except Exception as cycle_exception:
            print(f"[ERROR] Unhandled exception within cycle {loop_count + 1} for {server_alias}: {cycle_exception}", flush=True)
            import traceback
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()

        time_taken = time.time() - start_time
        sleep_duration = max(0.1, addon_options["check_interval_seconds"] - time_taken)
        
        # print(f"[{log_level.upper()}] Cycle {loop_count + 1} for {server_alias} took {time_taken:.2f}s. Sleeping for {sleep_duration:.2f}s.", flush=True)
        loop_count += 1

        for _ in range(int(sleep_duration / 0.1)):
            if not running: break
            time.sleep(0.1)
        if not running: break

# --- Global mqtt_handler_instance ---
mqtt_handler_instance = None

if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Controller Python Application Starting =====", flush=True)
    
    mqtt_handler_instance = mqtt_client.MqttClient()
    load_and_configure(mqtt_handler_instance) # This now loads servers_configs_list

    if not servers_configs_list: # Check if any servers were actually loaded and are ready
        print("[MAIN] No servers configured or loaded successfully. Exiting.", flush=True)
        sys.exit(1)
        
    # For Step 1, MQTT connects based on the first server's IP for device uniqueness if used in client_id
    first_server_ip_for_mqtt_client_id = servers_configs_list[0].get("idrac_ip", "unknown_ip").replace('.', '_')

    if addon_options.get("mqtt_host") and addon_options["mqtt_host"] != "YOUR_MQTT_BROKER_IP_OR_HOSTNAME":
        mqtt_handler_instance.client_id = f"ha_idrac_controller_{first_server_ip_for_mqtt_client_id}" # Temp client ID
        mqtt_handler_instance.connect() # Uses global MQTT settings from addon_options
    else:
        print("[INFO] MQTT host not configured or is default placeholder. MQTT client will not connect.", flush=True)
        mqtt_handler_instance = None

    web_server_port = int(os.getenv("INGRESS_PORT", 8099)) # Use Ingress port if available
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port,), daemon=True)
    web_thread.start()
    print(f"[MAIN] Admin Web Panel server starting in background thread on port {web_server_port}...", flush=True)

    try:
        # For Step 1, main_control_loop will operate on the first server configured in load_and_configure
        main_control_loop(mqtt_handler_instance)
    except Exception as e:
        print(f"[FATAL] Unhandled exception in main execution: {e}", flush=True)
        import traceback; traceback.print_exc(file=sys.stdout); sys.stdout.flush()
    finally:
        print("[MAIN] Main execution finished. Initiating final cleanup...", flush=True)
        # For Step 1, apply_dell_fan_control_profile uses the globally configured IPMI (first server)
        if servers_configs_list and ipmi_manager._IPMI_BASE_ARGS: # Check if IPMI was ever configured
            print(f"[MAIN] Attempting to set fans to Dell default profile for {servers_configs_list[0]['alias']}...", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        if mqtt_handler_instance and getattr(mqtt_handler_instance, 'is_connected', False):
            mqtt_handler_instance.disconnect()
        print("[MAIN] ===== HA iDRAC Controller Python Application Stopped =====", flush=True)
        sys.stdout.flush()
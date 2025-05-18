# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys
import signal
import threading
import re
import json # For saving status to file

from . import ipmi_manager
from . import web_server
from . import mqtt_client

# --- Global Variables ---
running = True
addon_options = {}
server_info = {
    "manufacturer": "Unknown", "model": "Unknown", "is_gen14_plus": False,
    "cpu_generic_temp_pattern": None, 
    "inlet_temp_name_pattern": None, 
    "exhaust_temp_name_pattern": None
}
app_config = {} 
loop_count = 0
current_parsed_status = { # For sharing with web_server via file
    "cpu_temps_c": [], "hottest_cpu_temp_c": None,
    "inlet_temp_c": None, "exhaust_temp_c": None,
    "target_fan_speed_percent": "N/A", "actual_fan_rpms": [],
    "last_updated": "Never"
}
STATUS_FILE = "/data/current_status.json"


# --- Graceful Shutdown & Helpers ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

def determine_server_generation(model_name): # (Keep this function as is)
    if not model_name: return False
    match = re.search(r"^[RT]\s?(\d)(\d)\d+", model_name.upper())
    if match:
        try:
            gen_indicator_digit = int(match.group(2))
            if gen_indicator_digit >= 4: return True
        except (IndexError, ValueError): pass
    return False

def celsius_to_fahrenheit(celsius): # (Keep this function as is)
    if celsius is None: return None
    return (celsius * 9/5) + 32

def fahrenheit_to_celsius(fahrenheit): # (Keep this function as is)
    if fahrenheit is None: return None
    return (fahrenheit - 32) * 5/9

def save_current_status_to_file(status_dict): # (Keep this function as is)
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(status_dict, f, indent=4)
    except (IOError, PermissionError) as e:
        print(f"[ERROR] Could not save status to {STATUS_FILE}: {e}", flush=True)

# --- Main Application Logic ---
def load_and_configure():
    global addon_options, app_config, server_info, mqtt_handler_instance # Make mqtt_handler_instance global for device_info
    print("[MAIN] Loading configuration and initializing...", flush=True)
    
    addon_options = { # (Keep existing option loading as is)
        "idrac_ip": os.getenv("IDRAC_IP"), "idrac_username": os.getenv("IDRAC_USERNAME"),
        "idrac_password": os.getenv("IDRAC_PASSWORD"),
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),
        "log_level": os.getenv("LOG_LEVEL", "info").lower(),
        "temperature_unit": os.getenv("TEMPERATURE_UNIT", "C").upper(),
        "base_fan_speed_percent": int(os.getenv("BASE_FAN_SPEED_PERCENT", "20")),
        "low_temp_threshold": int(os.getenv("LOW_TEMP_THRESHOLD", "45")),
        "high_temp_fan_speed_percent": int(os.getenv("HIGH_TEMP_FAN_SPEED_PERCENT", "50")),
        "critical_temp_threshold": int(os.getenv("CRITICAL_TEMP_THRESHOLD", "65")),
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "mqtt_port": int(os.getenv("MQTT_PORT", "1883")),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", "")
    }
    log_level = addon_options['log_level']
    print(f"[{log_level.upper()}] Add-on options loaded: IDRAC_IP={addon_options['idrac_ip']}, LogLevel={log_level}", flush=True)

    ipmi_manager.configure_ipmi(
        addon_options["idrac_ip"], addon_options["idrac_username"], 
        addon_options["idrac_password"], log_level=log_level
    )

    model_data = ipmi_manager.get_server_model_info()
    if model_data and model_data.get("model") != "Unknown":
        server_info.update(model_data)
        server_info["is_gen14_plus"] = determine_server_generation(server_info["model"])
        print(f"[{log_level.upper()}] Server: {server_info['manufacturer']} {server_info['model']} (Gen14+: {server_info['is_gen14_plus']})", flush=True)
    else:
        print(f"[WARNING] Could not determine server model.", flush=True)
    
    # Update MQTT client with device info for discovery messages
    if mqtt_handler_instance: # Ensure mqtt_handler_instance is initialized
        mqtt_handler_instance.set_device_info(
            server_info["manufacturer"], 
            server_info["model"], 
            addon_options["idrac_ip"]
        )

    server_info["cpu_generic_temp_pattern"] = r"^Temp$" 
    server_info["inlet_temp_name_pattern"] = r"Inlet Temp"
    server_info["exhaust_temp_name_pattern"] = r"Exhaust Temp"
    print(f"[{log_level.upper()}] Using temp patterns: CPU_generic='{server_info['cpu_generic_temp_pattern']}', Inlet='{server_info['inlet_temp_name_pattern']}', Exhaust='{server_info['exhaust_temp_name_pattern']}'", flush=True)

    app_config = web_server.load_app_config()
    print(f"[{log_level.upper()}] Loaded app config: {app_config}", flush=True)

    temp_unit = addon_options["temperature_unit"]
    if temp_unit == "F":
        addon_options["low_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["low_temp_threshold"])
        addon_options["critical_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (F input converted to C): Low={addon_options['low_temp_threshold_c']:.1f}C, Critical={addon_options['critical_temp_threshold_c']:.1f}C", flush=True)
    else:
        addon_options["low_temp_threshold_c"] = float(addon_options["low_temp_threshold"])
        addon_options["critical_temp_threshold_c"] = float(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (C input): Low={addon_options['low_temp_threshold_c']}C, Critical={addon_options['critical_temp_threshold_c']}C", flush=True)


def main_control_loop(mqtt_handler):
    global running, app_config, addon_options, server_info, loop_count, current_parsed_status
    log_level = addon_options['log_level']

    if not (addon_options["idrac_ip"] and addon_options["idrac_username"] and addon_options["idrac_password"]):
        print("[ERROR] iDRAC credentials not fully configured. Exiting.", flush=True)
        return 
    
    print(f"[{log_level.upper()}] Entering main control loop. Interval: {addon_options['check_interval_seconds']}s", flush=True)

    while running:
        start_time = time.time()
        print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} Start ---", flush=True)

        if loop_count > 0 and loop_count % 5 == 0:
             print(f"[{log_level.upper()}] Reloading app config from /data/app_config.json", flush=True)
             app_config = web_server.load_app_config()

        # --- Retrieve and Parse Temperatures ---
        raw_temp_sdr_data = ipmi_manager.retrieve_temperatures_raw()
        parsed_temperatures_c = {"cpu_temps": [], "inlet_temp": None, "exhaust_temp": None}
        if raw_temp_sdr_data:
            print(f"[{log_level.upper()}] RAW TEMP SDR DATA:\n{raw_temp_sdr_data}\n-------------------------", flush=True)
            parsed_temperatures_c = ipmi_manager.parse_temperatures(
                raw_temp_sdr_data,
                server_info["cpu_generic_temp_pattern"],
                server_info["inlet_temp_name_pattern"],
                server_info["exhaust_temp_name_pattern"]
            )
            print(f"[{log_level.upper()}] Parsed Temperatures (C): {parsed_temperatures_c}", flush=True)
        else:
            print(f"[WARNING] Failed to retrieve temp SDR data.", flush=True)

        # --- Retrieve and Parse Fan RPMs ---
        raw_fan_sdr_data = ipmi_manager.retrieve_fan_rpms_raw()
        parsed_fan_rpms = []
        if raw_fan_sdr_data:
            print(f"[{log_level.upper()}] RAW FAN SDR DATA:\n{raw_fan_sdr_data}\n-------------------------", flush=True)
            parsed_fan_rpms = ipmi_manager.parse_fan_rpms(raw_fan_sdr_data)
            print(f"[{log_level.upper()}] Parsed Fan RPMs: {parsed_fan_rpms}", flush=True)
        else:
            print(f"[WARNING] Failed to retrieve fan SDR data.", flush=True)


        # --- Determine Hottest CPU ---
        hottest_cpu_temp_c = None
        cpu_temps_list_c = parsed_temperatures_c.get("cpu_temps", [])
        if cpu_temps_list_c:
            hottest_cpu_temp_c = max(cpu_temps_list_c)
            print(f"[{log_level.upper()}] Hottest CPU Temp: {hottest_cpu_temp_c}°C from {cpu_temps_list_c}", flush=True)
        else:
            print(f"[WARNING] No CPU temperatures available for fan control.", flush=True)

        # --- Fan Control Logic ---
        target_fan_speed_display = "N/A" # For status and MQTT
        if hottest_cpu_temp_c is not None:
            low_thresh_c = addon_options["low_temp_threshold_c"]
            crit_thresh_c = addon_options["critical_temp_threshold_c"]
            
            if hottest_cpu_temp_c >= crit_thresh_c:
                print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) >= CRITICAL ({crit_thresh_c}°C). Dell auto fans.", flush=True)
                ipmi_manager.apply_dell_fan_control_profile()
                target_fan_speed_display = "Dell Auto"
            elif hottest_cpu_temp_c >= low_thresh_c:
                target_fan_speed_val = addon_options["high_temp_fan_speed_percent"]
                print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) >= LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                target_fan_speed_display = target_fan_speed_val
            else: 
                target_fan_speed_val = addon_options["base_fan_speed_percent"]
                print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) < LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                target_fan_speed_display = target_fan_speed_val
        else:
            print(f"[WARNING] Hottest CPU temp N/A. Applying Dell auto fans for safety.", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
            target_fan_speed_display = "Dell Auto (Safety)"
        
        # --- Update Shared Status File for Web UI ---
        status_to_save = {
            "cpu_temps_c": cpu_temps_list_c,
            "hottest_cpu_temp_c": hottest_cpu_temp_c,
            "inlet_temp_c": parsed_temperatures_c.get("inlet_temp"),
            "exhaust_temp_c": parsed_temperatures_c.get("exhaust_temp"),
            "target_fan_speed_percent": target_fan_speed_display,
            "actual_fan_rpms": parsed_fan_rpms, # List of {"name": ..., "rpm": ...}
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S %Z")
        }
        save_current_status_to_file(status_to_save)

        # --- MQTT Publishing ---
        if mqtt_handler and mqtt_handler.is_connected:
            # CPU Temps
            for i, cpu_temp_val in enumerate(cpu_temps_list_c):
                mqtt_handler.publish_sensor_state(sensor_type_slug=f"cpu_{i}_temp", value_dict={"temperature": cpu_temp_val})
            # Inlet/Exhaust
            if parsed_temperatures_c.get("inlet_temp") is not None:
                 mqtt_handler.publish_sensor_state(sensor_type_slug="inlet_temp", value_dict={"temperature": parsed_temperatures_c["inlet_temp"]})
            if parsed_temperatures_c.get("exhaust_temp") is not None:
                 mqtt_handler.publish_sensor_state(sensor_type_slug="exhaust_temp", value_dict={"temperature": parsed_temperatures_c["exhaust_temp"]})
            # Target Fan Speed
            if target_fan_speed_display not in ["N/A", "Dell Auto", "Dell Auto (Safety)"]:
                mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": int(target_fan_speed_display)})
            else: # Publish a non-numeric or specific state if auto
                 mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": None}) # Or publish string "Auto" if template handles it
            # Actual Fan RPMs
            for i, fan_info in enumerate(parsed_fan_rpms):
                # Ensure discovery for fan_X_rpm (e.g., fan_0_rpm, fan_1_rpm) was called in on_connect
                # The sensor_type_slug for discovery must match here.
                # For simplicity, let's use generic fan_X_rpm. You might want to use actual fan_info["name"] if stable.
                mqtt_handler.publish_sensor_state(sensor_type_slug=f"fan_{i}_rpm", value_dict={"rpm": fan_info["rpm"]})


        print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} End ---", flush=True)
        loop_count += 1
        
        time_taken = time.time() - start_time
        sleep_duration = max(0.1, addon_options["check_interval_seconds"] - time_taken)
        
        for _ in range(int(sleep_duration / 0.1)):
            if not running: break
            time.sleep(0.1)
        if not running: break

# --- Global mqtt_handler_instance needed for load_and_configure to set device_info ---
mqtt_handler_instance = None

if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Controller Python Application Starting =====", flush=True)
    
    # Initialize MQTT Client first so its instance is available for load_and_configure
    mqtt_handler_instance = mqtt_client.MqttClient(
        # Client ID will be more unique after load_and_configure sets device_info
    )

    load_and_configure() # Loads options, configures IPMI, gets server_info, sets device_info on mqtt_handler

    # Now connect MQTT, which will use the device_info for discovery
    if addon_options.get("mqtt_host") and addon_options["mqtt_host"] != "YOUR_MQTT_BROKER_IP_OR_HOSTNAME":
        # Update client_id if needed, though it's set at init
        mqtt_handler_instance.client_id = f"ha_idrac_controller_{addon_options.get('idrac_ip','unknown_ip')}"
        mqtt_handler_instance.broker_address = addon_options["mqtt_host"]
        mqtt_handler_instance.port = addon_options["mqtt_port"]
        mqtt_handler_instance.username = addon_options["mqtt_username"]
        mqtt_handler_instance.password = addon_options["mqtt_password"]
        if mqtt_handler_instance.username: 
             mqtt_handler_instance.client.username_pw_set(mqtt_handler_instance.username, mqtt_handler_instance.password)
        mqtt_handler_instance.connect()
    else:
        print("[INFO] MQTT host not configured. MQTT client will not connect.", flush=True)
        mqtt_handler_instance = None 

    web_server_port = 8099 
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port,), daemon=True)
    web_thread.start()
    print(f"[MAIN] Admin Web Panel server starting in background thread on port {web_server_port}...", flush=True)

    try:
        main_control_loop(mqtt_handler_instance)
    except Exception as e:
        print(f"[FATAL] Unhandled exception in main execution: {e}", flush=True)
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
    finally:
        print("[MAIN] Main execution finished. Initiating final cleanup...", flush=True)
        if addon_options.get("idrac_ip") and ipmi_manager._IPMI_BASE_ARGS: 
            print("[MAIN] Attempting to set fans to Dell default profile...", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        if mqtt_handler_instance and getattr(mqtt_handler_instance, 'is_connected', False):
            mqtt_handler_instance.disconnect()
        print("[MAIN] ===== HA iDRAC Controller Python Application Stopped =====", flush=True)
        sys.stdout.flush()
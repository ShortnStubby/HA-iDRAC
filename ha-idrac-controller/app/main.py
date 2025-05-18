# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys
import signal
import threading
import re

# Use relative imports for modules within the same package
from . import ipmi_manager
from . import web_server
from . import mqtt_client

# --- Global Variables ---
running = True
addon_options = {}
server_info = {
    "manufacturer": "Unknown", "model": "Unknown", "is_gen14_plus": False,
    "cpu_generic_temp_pattern": None, # Will be set based on R720 output
    "inlet_temp_name_pattern": None,
    "exhaust_temp_name_pattern": None
}
app_config = {} # For settings from /data/app_config.json (e.g., advanced fan curve)
loop_count = 0 # Initialize loop_count globally or pass to main_control_loop

# --- Graceful Shutdown Handler ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# --- Server Generation Detection ---
def determine_server_generation(model_name):
    if not model_name: return False
    match = re.search(r"^[RT]\s?(\d)(\d)\d+", model_name.upper())
    if match:
        try:
            gen_indicator_digit = int(match.group(2))
            if gen_indicator_digit >= 4: return True
        except (IndexError, ValueError): pass
    return False

# --- Temperature Unit Conversion ---
def celsius_to_fahrenheit(celsius):
    if celsius is None: return None
    return (celsius * 9/5) + 32

def fahrenheit_to_celsius(fahrenheit):
    if fahrenheit is None: return None
    return (fahrenheit - 32) * 5/9

# --- Main Application Logic ---
def load_and_configure():
    global addon_options, app_config, server_info
    print("[MAIN] Loading configuration and initializing...", flush=True)
    
    addon_options = {
        "idrac_ip": os.getenv("IDRAC_IP"),
        "idrac_username": os.getenv("IDRAC_USERNAME"),
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
    log_level = addon_options['log_level'] # For convenience
    print(f"[{log_level.upper()}] Add-on options loaded: IDRAC_IP={addon_options['idrac_ip']}, LogLevel={log_level}", flush=True)

    ipmi_manager.configure_ipmi(
        addon_options["idrac_ip"],
        addon_options["idrac_username"],
        addon_options["idrac_password"],
        log_level=log_level
    )

    model_data = ipmi_manager.get_server_model_info()
    if model_data and model_data.get("model") != "Unknown":
        server_info.update(model_data)
        server_info["is_gen14_plus"] = determine_server_generation(server_info["model"])
        print(f"[{log_level.upper()}] Server: {server_info['manufacturer']} {server_info['model']} (Gen14+: {server_info['is_gen14_plus']})", flush=True)
    else:
        print(f"[WARNING] Could not determine server model. Temperature parsing might be affected.", flush=True)

    # Based on R720 output "Temp             | 0Eh | ok  |  3.1 | 43 degrees C"
    server_info["cpu_generic_temp_pattern"] = r"^Temp\s" 
    server_info["inlet_temp_name_pattern"] = r"Inlet Temp"
    server_info["exhaust_temp_name_pattern"] = r"Exhaust Temp"
    print(f"[{log_level.upper()}] Using temp patterns: CPU_generic='{server_info['cpu_generic_temp_pattern']}', Inlet='{server_info['inlet_temp_name_pattern']}', Exhaust='{server_info['exhaust_temp_name_pattern']}'", flush=True)

    app_config = web_server.load_app_config()
    print(f"[{log_level.upper()}] Loaded app config (e.g., advanced fan curve): {app_config}", flush=True)

    # Convert thresholds to Celsius if user configured Fahrenheit, for internal consistency
    # Store these converted thresholds also in addon_options for easy access in the loop
    temp_unit = addon_options["temperature_unit"]
    if temp_unit == "F":
        addon_options["low_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["low_temp_threshold"])
        addon_options["critical_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (F input converted to C for internal use): Low={addon_options['low_temp_threshold_c']:.1f}C, Critical={addon_options['critical_temp_threshold_c']:.1f}C", flush=True)
    else: # Already Celsius
        addon_options["low_temp_threshold_c"] = float(addon_options["low_temp_threshold"]) # Ensure float for comparison
        addon_options["critical_temp_threshold_c"] = float(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (C input): Low={addon_options['low_temp_threshold_c']}C, Critical={addon_options['critical_temp_threshold_c']}C", flush=True)


def main_control_loop(mqtt_handler):
    global running, app_config, addon_options, server_info, loop_count # Ensure loop_count is accessible
    log_level = addon_options['log_level']

    if not (addon_options["idrac_ip"] and addon_options["idrac_username"] and addon_options["idrac_password"]):
        print("[ERROR] iDRAC credentials not fully configured. Exiting control loop.", flush=True)
        return 

    if mqtt_handler and mqtt_handler.is_connected:
        print(f"[{log_level.upper()}] Publishing initial MQTT discovery messages (if any defined).", flush=True)
        # Example: Publish discovery for up to 4 CPUs
        for i in range(4): # Assuming max 4 CPUs for discovery
            mqtt_handler.publish_cpu_temp_discovery(cpu_id=str(i))
        # TODO: Add other discovery messages here (inlet, exhaust, fan speeds, disk health)
    
    print(f"[{log_level.upper()}] Entering main control loop. Check interval: {addon_options['check_interval_seconds']}s", flush=True)

    while running:
        start_time = time.time()
        print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} Start ---", flush=True)

        if loop_count > 0 and loop_count % 5 == 0: # Reload app_config (e.g. advanced fan curve) periodically
             print(f"[{log_level.upper()}] Reloading app config from /data/app_config.json", flush=True)
             app_config = web_server.load_app_config()

        raw_sdr_data = ipmi_manager.retrieve_temperatures_raw()
        parsed_temperatures_c = {} 

        if raw_sdr_data:
            parsed_temperatures_c = ipmi_manager.parse_temperatures(
                raw_sdr_data,
                server_info["cpu_generic_temp_pattern"],
                server_info["inlet_temp_name_pattern"],
                server_info["exhaust_temp_name_pattern"]
            )
            print(f"[{log_level.upper()}] Parsed Temperatures (Celsius): {parsed_temperatures_c}", flush=True)
            
            if mqtt_handler and mqtt_handler.is_connected:
                for i, cpu_temp_val in enumerate(parsed_temperatures_c.get("cpu_temps", [])):
                    mqtt_handler.publish_temperature(sensor_name=f"idrac_cpu_{i}_temp", temperature_value=cpu_temp_val)
                if parsed_temperatures_c.get("inlet_temp") is not None:
                     # TODO: mqtt_handler.publish_inlet_temp_discovery() if not done
                     mqtt_handler.publish_temperature(sensor_name="idrac_inlet_temp", temperature_value=parsed_temperatures_c["inlet_temp"])
                if parsed_temperatures_c.get("exhaust_temp") is not None:
                     # TODO: mqtt_handler.publish_exhaust_temp_discovery()
                     mqtt_handler.publish_temperature(sensor_name="idrac_exhaust_temp", temperature_value=parsed_temperatures_c["exhaust_temp"])
        else:
            print(f"[WARNING] Failed to retrieve SDR data this cycle.", flush=True)

        hottest_cpu_temp_c = None
        cpu_temps_list_c = parsed_temperatures_c.get("cpu_temps", [])
        if cpu_temps_list_c:
            hottest_cpu_temp_c = max(cpu_temps_list_c)
            print(f"[{log_level.upper()}] Hottest CPU Temp: {hottest_cpu_temp_c}°C from list: {cpu_temps_list_c}", flush=True)
        else:
            print(f"[WARNING] No CPU temperatures available for fan control.", flush=True)

        if hottest_cpu_temp_c is not None:
            low_thresh_c = addon_options["low_temp_threshold_c"]
            crit_thresh_c = addon_options["critical_temp_threshold_c"]
            
            if hottest_cpu_temp_c >= crit_thresh_c:
                print(f"[{log_level.upper()}] CPU Temp ({hottest_cpu_temp_c}°C) at or above CRITICAL ({crit_thresh_c}°C). Reverting to Dell auto fan control.", flush=True)
                ipmi_manager.apply_dell_fan_control_profile()
            elif hottest_cpu_temp_c >= low_thresh_c:
                target_fan_speed = addon_options["high_temp_fan_speed_percent"]
                print(f"[{log_level.upper()}] CPU Temp ({hottest_cpu_temp_c}°C) is HIGH (>= {low_thresh_c}°C). Setting fan to {target_fan_speed}%", flush=True)
                ipmi_manager.apply_user_fan_control_profile(target_fan_speed)
            else: 
                target_fan_speed = addon_options["base_fan_speed_percent"]
                print(f"[{log_level.upper()}] CPU Temp ({hottest_cpu_temp_c}°C) is LOW (< {low_thresh_c}°C). Setting fan to {target_fan_speed}%", flush=True)
                ipmi_manager.apply_user_fan_control_profile(target_fan_speed)
        else:
            print(f"[WARNING] Hottest CPU temperature not available. Applying Dell auto fan control for safety.", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        
        print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} End ---", flush=True)
        loop_count += 1
        
        time_taken = time.time() - start_time
        sleep_duration = max(0.1, addon_options["check_interval_seconds"] - time_taken)
        
        for _ in range(int(sleep_duration / 0.1)): # Check running flag frequently
            if not running: break
            time.sleep(0.1)
        if not running: break

if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Controller Python Application Starting =====", flush=True)
    
    load_and_configure() 

    mqtt_handler_instance = mqtt_client.MqttClient(
        client_id=f"ha_idrac_controller_{addon_options.get('idrac_ip','unknown_ip')}" # Use a unique client ID
    )
    if addon_options.get("mqtt_host") and addon_options["mqtt_host"] != "YOUR_MQTT_BROKER_IP_OR_HOSTNAME": # Check for actual host
        mqtt_handler_instance.broker_address = addon_options["mqtt_host"]
        mqtt_handler_instance.port = addon_options["mqtt_port"]
        mqtt_handler_instance.username = addon_options["mqtt_username"]
        mqtt_handler_instance.password = addon_options["mqtt_password"]
        if mqtt_handler_instance.username: 
             mqtt_handler_instance.client.username_pw_set(mqtt_handler_instance.username, mqtt_handler_instance.password)
        mqtt_handler_instance.connect()
    else:
        print("[INFO] MQTT host not configured or is default placeholder. MQTT client will not connect.", flush=True)
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
            print("[MAIN] Attempting to set fans to Dell default profile as a final safety measure...", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        if mqtt_handler_instance and getattr(mqtt_handler_instance, 'is_connected', False): # Check if attribute exists and is true
            mqtt_handler_instance.disconnect()
        print("[MAIN] ===== HA iDRAC Controller Python Application Stopped =====", flush=True)
        sys.stdout.flush()
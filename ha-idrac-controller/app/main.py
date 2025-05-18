# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys
import signal
import threading
import re # For server generation detection

# Use relative imports for modules within the same package (the 'app' directory)
from . import ipmi_manager
from . import web_server
from . import mqtt_client # Placeholder for now

# --- Global Variables ---
running = True  # Flag to control the main loop
addon_options = {} # To store configuration passed from run.sh
server_info = { # To store server model details and generation
    "manufacturer": "Unknown", 
    "model": "Unknown", 
    "is_gen14_plus": False,
    "cpu1_temp_name_pattern": None, # Will be set based on generation for parsing
    "cpu2_temp_name_pattern": None  # Will be set based on generation for parsing
}
app_config = {} # For settings from /data/app_config.json (e.g., fan curve)

# --- Graceful Shutdown Handler ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

# Register signal handlers
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# --- Server Generation Detection ---
def determine_server_generation(model_name):
    if not model_name:
        return False
    # Regex based on the shell script: .*[RT][[:space:]]?[0-9][4-9]0.*
    # This looks for models like R740, T640, R750, R6515 etc.
    # [RT]       : Starts with R or T
    # \s?        : Optional space (python re syntax)
    # \d         : First digit of model number (e.g., 6, 7, 8 for Rx_x_0)
    # [4-9]      : Second digit (Gen indicator: 40 series and up are Gen14+)
    # \d*0       : Ends in 0, allowing for 2 or 3 digit model numbers like 640 or 6515 (where 5 is the new gen indicator)
    # Let's refine the regex slightly for common Dell PowerEdge R/Txxx or R/Txxxx patterns
    # Example: R740, T640, R650, R7525 (where the 3rd digit is key for Gen X5X)
    # Gen14: x4x (e.g. R740)
    # Gen15: x5x (e.g. R750)
    # Gen16: x6x (e.g. R760)
    # So, if the second character of the numeric part (after R/T and optional space) is 4 or greater
    match = re.search(r"^[RT]\s?(\d)(\d)\d+", model_name.upper()) # Match R/T followed by 3+ digits
    if match:
        try:
            # Example R740: first_digit=7, gen_indicator_digit=4
            # Example R6515: first_digit=6, gen_indicator_digit=5
            gen_indicator_digit = int(match.group(2)) 
            if gen_indicator_digit >= 4: # 40 series (Gen14), 50 series (Gen15), etc.
                return True
        except (IndexError, ValueError):
            pass # Could not parse digits
    return False

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
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "mqtt_port": int(os.getenv("MQTT_PORT", "1883")),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", "")
    }

    print(f"[{addon_options['log_level'].upper()}] Add-on options loaded: IDRAC_IP={addon_options['idrac_ip']}", flush=True)

    ipmi_manager.configure_ipmi(
        addon_options["idrac_ip"],
        addon_options["idrac_username"],
        addon_options["idrac_password"],
        log_level=addon_options["log_level"]
    )

    model_data = ipmi_manager.get_server_model_info()
    if model_data and model_data.get("model") != "Unknown":
        server_info.update(model_data)
        server_info["is_gen14_plus"] = determine_server_generation(server_info["model"])
        print(f"[{addon_options['log_level'].upper()}] Server: {server_info['manufacturer']} {server_info['model']} (Gen14+: {server_info['is_gen14_plus']})", flush=True)
    else:
        print("[WARNING] Could not determine server model. Temperature parsing might be affected.", flush=True)

    # Set sensor name patterns based on generation for ipmi_manager.parse_temperatures
    # These are examples; you'll need to inspect your `ipmitool sdr type temperature` output
    # The original shell script used indices, which is harder with less structured parsing.
    # We'll aim for name patterns.
    # For Gen13 and older (e.g., R730): CPU temps might be "CPU1 Temp", "CPU2 Temp"
    # For Gen14+ (e.g., R740): Might be similar or have specific identifiers.
    # This requires inspecting your server's SDR output.
    # As a placeholder for now, let's assume simple naming for CPU1.
    server_info["cpu1_temp_name_pattern"] = r"CPU1 Temp|Temp CPU1|CPU0[1-9]\sTemp|Proc\s1\sTemp" # Example patterns
    server_info["cpu2_temp_name_pattern"] = r"CPU2 Temp|Temp CPU2|CPU1[0-9]\sTemp|Proc\s2\sTemp" # Example patterns
    # Inlet/Exhaust names are usually more consistent:
    server_info["inlet_temp_name_pattern"] = r"Inlet Temp|Ambient Temp|System Board Inlet Temp"
    server_info["exhaust_temp_name_pattern"] = r"Exhaust Temp|System Board Exhaust Temp"


    # Load persistent app config (fan curve etc.)
    app_config = web_server.load_app_config() # web_server.py should define this
    print(f"[{addon_options['log_level'].upper()}] Loaded app config (fan curve, etc.): {app_config}", flush=True)

def main_control_loop(mqtt_handler):
    global running, app_config
    
    if not (addon_options["idrac_ip"] and addon_options["idrac_username"] and addon_options["idrac_password"]):
        print("[ERROR] iDRAC credentials not fully configured in add-on options. Exiting control loop.", flush=True)
        return # Exit if core config is missing

    if mqtt_handler and mqtt_handler.is_connected:
        mqtt_handler.publish_cpu_temp_discovery(cpu_id="1") # Example for CPU1
        # TODO: Add discovery for CPU2, Inlet, Exhaust, Fans, Disk Health etc.
        # TODO: Publish initial availability 'online'
        pass
    
    print(f"[{addon_options['log_level'].upper()}] Entering main control loop. Check interval: {addon_options['check_interval_seconds']}s", flush=True)

    while running:
        start_time = time.time()
        log_level_current = addon_options['log_level'] # Use consistently

        # Periodically reload app_config in case it changed via web UI
        # More advanced would be a signal or event from web_server.py
        if loop_count % 5 == 0 : # Reload approx every 5 cycles
             print(f"[{log_level_current.upper()}] Reloading app config from /data/app_config.json", flush=True)
             app_config = web_server.load_app_config()

        print(f"[{log_level_current.upper()}] --- Cycle Start ---", flush=True)

        raw_sdr_data = ipmi_manager.retrieve_temperatures_raw()
        parsed_temperatures = {}

        if raw_sdr_data:
            # Pass the determined sensor name patterns for parsing
            parsed_temperatures = ipmi_manager.parse_temperatures(
                raw_sdr_data,
                server_info["cpu1_temp_name_pattern"],
                server_info["cpu2_temp_name_pattern"],
                server_info["inlet_temp_name_pattern"],
                server_info["exhaust_temp_name_pattern"]
            )
            print(f"[{log_level_current.upper()}] Parsed Temperatures: {parsed_temperatures}", flush=True)
            if mqtt_handler and mqtt_handler.is_connected:
                if parsed_temperatures.get("cpu1_temp") is not None:
                    mqtt_handler.publish_temperature(sensor_name="idrac_cpu1_temp", temperature_value=parsed_temperatures["cpu1_temp"])
                # TODO: Publish other temps
        else:
            print(f"[WARNING] Failed to retrieve SDR data this cycle.", flush=True)

        # --- Fan Control Logic (Placeholder - to be implemented next) ---
        if parsed_temperatures.get("cpu1_temp") is not None:
            cpu1_temp = parsed_temperatures["cpu1_temp"]
            fan_curve = app_config.get("fan_curve", [])
            target_fan_speed = 20 # Default minimum
            
            # Ensure fan_curve is sorted by temp (should be done on save by web_server)
            # fan_curve.sort(key=lambda x: x['temp']) 

            for point in reversed(fan_curve): # Iterate from highest temp downwards
                if "temp" in point and "speed" in point and cpu1_temp >= point["temp"]:
                    target_fan_speed = point["speed"]
                    break 
            
            print(f"[{log_level_current.upper()}] Fan curve: CPU1 Temp {cpu1_temp}°C -> Target Fan Speed {target_fan_speed}%", flush=True)
            # ipmi_manager.apply_user_fan_control_profile(target_fan_speed) # UNCOMMENT WHEN READY TO TEST FAN CONTROL
            if mqtt_handler and mqtt_handler.is_connected:
                # TODO: Publish target fan speed
                pass
        else:
            print(f"[WARNING] CPU1 temperature not available. Using default fan logic or Dell auto.", flush=True)
            # Consider: ipmi_manager.apply_dell_fan_control_profile() # Safety fallback

        # TODO: Disk health checks

        print(f"[{log_level_current.upper()}] --- Cycle End ---", flush=True)
        
        # Calculate time taken and sleep for the remainder of the interval
        time_taken = time.time() - start_time
        sleep_duration = max(0.1, addon_options["check_interval_seconds"] - time_taken) # Ensure at least a small sleep
        
        # Check running flag frequently within sleep for faster shutdown
        for _ in range(int(sleep_duration / 0.1)): # Check every 100ms
            if not running:
                break
            time.sleep(0.1)
        if not running:
            break
loop_count = 0 # Initialize loop_count before the loop

if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Controller Python Application Starting =====", flush=True)
    
    load_and_configure() # Load options and initial iDRAC info

    # Initialize and connect MQTT Client
    # Ensure MQTT options are available in addon_options if needed by MqttClient constructor
    mqtt_handler = mqtt_client.MqttClient(client_id=f"ha_idrac_controller_{addon_options.get('idrac_ip','default')}")
    if addon_options.get("mqtt_host"): # Only connect if MQTT host is configured
        mqtt_handler.broker_address = addon_options["mqtt_host"]
        mqtt_handler.port = addon_options["mqtt_port"]
        mqtt_handler.username = addon_options["mqtt_username"]
        mqtt_handler.password = addon_options["mqtt_password"]
        if mqtt_handler.username and mqtt_handler.password:
             mqtt_handler.client.username_pw_set(mqtt_handler.username, mqtt_handler.password)
        mqtt_handler.connect() # Starts its own loop in a thread
    else:
        print("[INFO] MQTT host not configured. MQTT client will not connect.", flush=True)
        mqtt_handler = None # Ensure it's None if not used

    # Start the Flask Web Server in a background thread
    web_server_port = 8099 # Should match ingress_port in config.yaml
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port,), daemon=True)
    web_thread.start()
    print(f"[MAIN] Admin Web Panel server starting in background thread on port {web_server_port}...", flush=True)

    try:
        main_control_loop(mqtt_handler)
    except Exception as e:
        print(f"[FATAL] Unhandled exception in main execution: {e}", flush=True)
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
    finally:
        print("[MAIN] Main execution finished. Initiating final cleanup...", flush=True)
        if addon_options.get("idrac_ip") and ipmi_manager._IPMI_BASE_ARGS: # Check if IPMI was configured
            print("[MAIN] Attempting to set fans to Dell default profile as a final safety measure...", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        if mqtt_handler and mqtt_handler.is_connected:
            mqtt_handler.disconnect()
        print("[MAIN] ===== HA iDRAC Controller Python Application Stopped =====", flush=True)
        sys.stdout.flush()
# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import signal # For graceful shutdown
import threading # To run web server and MQTT client in background

# Import your custom modules
from . import ipmi_manager # Use relative import for modules within the same package
from . import web_server
from . import mqtt_client # Assuming you have mqtt_client.py

# --- Global Variables ---
# Flag to indicate if the application should keep running
running = True
# To store the server model info, including generation determination
server_info = {"model": "Unknown", "manufacturer": "Unknown", "is_gen14_plus": False}
# Store for add-on options and app config (like fan curve)
addon_options = {}
app_config = {} # Loaded from /data/app_config.json via web_server module

# --- Graceful Shutdown Handler ---
def graceful_shutdown(signum, frame):
    global running
    print("[INFO] Shutdown signal received. Cleaning up...")
    running = False
    # Further cleanup (like setting fans to auto) will happen in the main loop's finally block

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# --- Helper to load config and options ---
def load_configuration():
    global addon_options, app_config, server_info
    addon_options = {
        "idrac_ip": os.getenv("IDRAC_IP"),
        "idrac_username": os.getenv("IDRAC_USERNAME"),
        "idrac_password": os.getenv("IDRAC_PASSWORD"),
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),
        "log_level": os.getenv("LOG_LEVEL", "info").lower(),
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"), # Default for HA built-in
        "mqtt_port": int(os.getenv("MQTT_PORT", "1883")),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", "")
    }
    
    # Configure IPMI manager with credentials and log level
    ipmi_manager.configure_ipmi(
        addon_options["idrac_ip"],
        addon_options["idrac_username"],
        addon_options["idrac_password"],
        log_level=addon_options["log_level"] # Pass log_level here
    )
    
    # Load app-specific config (fan curve etc.) from /data via web_server's helper
    app_config = web_server.load_app_config()
    print(f"[{addon_options['log_level'].upper()}] Loaded app config: {app_config}")

    # Get server model to determine generation for temperature parsing
    model_data = ipmi_manager.get_server_model_info()
    if model_data:
        server_info.update(model_data)
        # Basic Gen14+ check (adapt regex from shell script)
        # Example: R740, T640, R6515 etc.
        if server_info["model"] and re.search(r"[RT]\s?\d?[4-9]\d{1,2}", server_info["model"], re.IGNORECASE):
            server_info["is_gen14_plus"] = True
        print(f"[{addon_options['log_level'].upper()}] Server Model: {server_info['model']}, Gen14+: {server_info['is_gen14_plus']}")


def main_control_loop(mqtt):
    global running, app_config # Allow modification if settings are reloaded

    load_configuration() # Load initial config

    if not (addon_options["idrac_ip"] and addon_options["idrac_username"] and addon_options["idrac_password"]):
        print("[ERROR] iDRAC credentials not fully configured. Exiting control loop.")
        running = False # Stop the loop if essential config is missing
        return

    # Publish MQTT Discovery messages once on startup if connected
    if mqtt and mqtt.is_connected:
        mqtt.publish_cpu_temp_discovery(cpu_id="1") # For CPU1
        # TODO: Add discovery for CPU2, Inlet, Exhaust, Fans, Disk Health etc.

    while running:
        start_time = time.time()
        
        # Reload app_config periodically or upon signal if implementing live updates
        # For simplicity now, it's loaded once unless web_server signals a change (TODO)
        # app_config = web_server.load_app_config() # If implementing dynamic reload

        raw_sdr_data = ipmi_manager.retrieve_temperatures_raw()
        temperatures = {} # This should be populated by a parsing function

        if raw_sdr_data:
            # TODO: Implement a robust parsing function in ipmi_manager
            # temperatures = ipmi_manager.parse_temperatures(raw_sdr_data, server_info["is_gen14_plus"])
            # For now, let's simulate a temperature for testing the loop
            print(f"[{addon_options['log_level'].upper()}] Raw SDR data retrieved (first 100 chars): {raw_sdr_data[:100]}")
            # Simulate CPU1 temp for logic testing
            temperatures["cpu1_temp"] = 55 # Replace with actual parsed temp
        else:
            print(f"[WARNING] Failed to retrieve temperatures this cycle.")

        if "cpu1_temp" in temperatures:
            cpu1_temp = temperatures["cpu1_temp"]
            print(f"[{addon_options['log_level'].upper()}] Current CPU1 Temp: {cpu1_temp}°C")
            if mqtt and mqtt.is_connected:
                mqtt.publish_temperature(sensor_name="idrac_cpu1_temp", temperature_value=cpu1_temp)

            # --- Fan Curve Logic ---
            target_fan_speed = 20 # Default minimum fan speed
            fan_curve = app_config.get("fan_curve", [])
            
            # Ensure fan_curve is sorted by temperature
            # fan_curve.sort(key=lambda x: x['temp']) # Already sorted when saved in web_server

            for point in reversed(fan_curve): # Iterate from highest temp downwards
                if cpu1_temp >= point["temp"]:
                    target_fan_speed = point["speed"]
                    break # Found the highest applicable tier
            
            print(f"[{addon_options['log_level'].upper()}] Fan curve applied. Target speed: {target_fan_speed}% for CPU temp {cpu1_temp}°C")
            ipmi_manager.apply_user_fan_control_profile(target_fan_speed)
            if mqtt and mqtt.is_connected:
                # TODO: Publish target fan speed, actual fan speed if available
                pass
        else:
            # Could not get CPU temp, maybe set fans to a safe default or revert to Dell auto
            print(f"[WARNING] CPU1 temperature not available. Not adjusting fans this cycle.")
            # Consider: ipmi_manager.apply_dell_fan_control_profile() for safety

        # TODO: Add disk health check and MQTT publishing
        # TODO: Add other sensor monitoring (inlet, exhaust, actual fan RPMs)

        # Calculate time taken and sleep for the remainder of the interval
        time_taken = time.time() - start_time
        sleep_duration = max(0, addon_options["check_interval_seconds"] - time_taken)
        if running: # Only sleep if we are still supposed to be running
            time.sleep(sleep_duration)

if __name__ == "__main__":
    print("[INFO] ===== HA iDRAC Controller Add-on Starting =====")
    
    # Initialize and connect MQTT Client
    mqtt_handler = mqtt_client.MqttClient()
    mqtt_handler.connect() # This starts its own loop in a thread

    # Start the Flask Web Server in a background thread
    # The web_server.py should define run_web_server()
    # Ensure web_server.py can access addon_options if needed, or pass them
    web_server_port = 8099 # Should match ingress_port in config.yaml
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port,), daemon=True)
    web_thread.start()
    print(f"[INFO] Admin Web Panel server starting in background thread on port {web_server_port}...")

    try:
        main_control_loop(mqtt_handler) # Pass MQTT client to the loop
    except Exception as e:
        print(f"[FATAL] Unhandled exception in main control loop: {e}")
    finally:
        print("[INFO] Main control loop ended. Initiating final cleanup...")
        if addon_options.get("idrac_ip"): # Check if IPMI was configured
            ipmi_manager.apply_dell_fan_control_profile() # Safety: set fans to auto on exit
            print("[INFO] Set fans to Dell default profile as a final safety measure.")
        if mqtt_handler:
            mqtt_handler.disconnect()
        print("[INFO] ===== HA iDRAC Controller Add-on Stopped =====")
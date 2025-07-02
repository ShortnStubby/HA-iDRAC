# HA-iDRAC/ha-idrac-controller-dev/app/main.py
import os
import time
import sys
import signal
import threading
import re
import json
from .ipmi_manager import IPMIManager
from .mqtt_client import MqttClient
from . import web_server

# --- Global Variables ---
running = True
threads = []
status_lock = threading.Lock()
ALL_SERVERS_STATUS = {}
STATUS_FILE = "/data/current_status.json"

# --- Graceful Shutdown ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# --- Server Worker Class ---
class ServerWorker:
    def __init__(self, server_config, global_opts):
        self.config = server_config
        self.global_opts = global_opts
        self.alias = self.config['alias']
        self.log_level = self.global_opts['log_level']
        self.running = True
        
        self.ipmi = IPMIManager(
            ip=self.config['idrac_ip'],
            user=self.config['idrac_username'],
            password=self.config['idrac_password'],
            log_level=self.log_level
        )
        
        self.mqtt = MqttClient(client_id=f"ha_idrac_{self.alias}")
        self.server_info = {}
        self.discovered_sensors = set()

    def _log(self, level, message):
        print(f"[{level.upper()}] [{self.alias}] {message}", flush=True)

    def _initialize(self):
        self._log("info", "Initializing server worker...")
        
        model_data = self.ipmi.get_server_model_info()
        if model_data:
            self.server_info.update(model_data)
        
        self.mqtt.configure_broker(
            self.global_opts["mqtt_host"],
            self.global_opts["mqtt_port"],
            self.global_opts["mqtt_username"],
            self.global_opts["mqtt_password"],
            self.log_level
        )
        self.mqtt.set_device_info(
            server_alias=self.alias,
            manufacturer=self.server_info.get("manufacturer"),
            model=self.server_info.get("model"),
            ip_address=self.config.get("idrac_ip")
        )
        self.mqtt.connect()
        time.sleep(2) 
        return True

    def run(self):
        if not self._initialize():
            self._log("error", "Initialization failed. Stopping worker.")
            return

        while self.running and running:
            start_time = time.time()
            
            raw_temp_data = self.ipmi.retrieve_temperatures_raw()
            if raw_temp_data is None:
                self.mqtt.publish(self.mqtt.availability_topic, "offline", retain=True)
                self._log("warning", "Failed to retrieve data from iDRAC. Server may be offline. Retrying in 60s.")
                time.sleep(60)
                continue

            self.mqtt.publish(self.mqtt.availability_topic, "online", retain=True)

            temps = self.ipmi.parse_temperatures(raw_temp_data, r"Temp", r"Inlet Temp", r"Exhaust Temp")
            fans = self.ipmi.parse_fan_rpms(self.ipmi.retrieve_fan_rpms_raw())
            power = self.ipmi.parse_power_consumption(self.ipmi.retrieve_power_sdr_raw())

            hottest_cpu = max(temps['cpu_temps']) if temps['cpu_temps'] else None
            target_fan_speed = "Dell Auto"
            if hottest_cpu is not None:
                low_thresh = self.config.get('low_temp_threshold', self.global_opts['low_temp_threshold'])
                crit_thresh = self.config.get('critical_temp_threshold', self.global_opts['critical_temp_threshold'])
                high_fan = self.config.get('high_temp_fan_speed_percent', self.global_opts['high_temp_fan_speed_percent'])
                base_fan = self.config.get('base_fan_speed_percent', self.global_opts['base_fan_speed_percent'])

                if hottest_cpu >= crit_thresh:
                    self.ipmi.apply_dell_fan_control_profile()
                    target_fan_speed = "Dell Auto (Critical)"
                elif hottest_cpu >= low_thresh:
                    target_fan_speed = high_fan
                    self.ipmi.apply_user_fan_control_profile(target_fan_speed)
                else:
                    target_fan_speed = base_fan
                    self.ipmi.apply_user_fan_control_profile(target_fan_speed)

            status_data = {
                "alias": self.alias, "ip": self.config['idrac_ip'],
                "cpu_temps_c": temps['cpu_temps'], "hottest_cpu_temp_c": hottest_cpu,
                "inlet_temp_c": temps['inlet_temp'], "exhaust_temp_c": temps['exhaust_temp'],
                "power_consumption_watts": power, "actual_fan_rpms": fans,
                "target_fan_speed_percent": target_fan_speed,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S %Z")
            }
            with status_lock:
                ALL_SERVERS_STATUS[self.alias] = status_data
            
            self._publish_mqtt_data(status_data)

            time_taken = time.time() - start_time
            sleep_duration = max(0.1, self.global_opts["check_interval_seconds"] - time_taken)
            self._log("debug", f"Cycle took {time_taken:.2f}s. Sleeping for {sleep_duration:.2f}s.")
            time.sleep(sleep_duration)

        self.cleanup()

    def _publish_mqtt_data(self, status):
        all_sensors = {
            "connectivity": {"component": "binary_sensor", "name": "Status", "device_class": "connectivity"},
            "hottest_cpu_temp": {"component": "sensor", "name": "Hottest CPU Temp", "device_class": "temperature", "unit": "°C"},
            "inlet_temp": {"component": "sensor", "name": "Inlet Temperature", "device_class": "temperature", "unit": "°C"},
            "exhaust_temp": {"component": "sensor", "name": "Exhaust Temperature", "device_class": "temperature", "unit": "°C"},
            "power": {"component": "sensor", "name": "Power Consumption", "device_class": "power", "unit": "W", "state_class": "measurement", "icon": "mdi:flash"},
            "target_fan_speed": {"component": "sensor", "name": "Target Fan Speed", "unit": "%", "icon": "mdi:fan-chevron-up"},
        }
        for i, temp in enumerate(status.get('cpu_temps_c', [])):
            all_sensors[f"cpu_{i}_temp"] = {"component": "sensor", "name": f"CPU {i} Temperature", "device_class": "temperature", "unit": "°C"}
        for fan in status.get('actual_fan_rpms', []):
            slug = f"fan_{re.sub(r'[^a-zA-Z0-9_]+', '', fan['name']).lower()}_rpm"
            all_sensors[slug] = {"component": "sensor", "name": f"{fan['name']} RPM", "unit": "RPM", "icon": "mdi:fan"}

        for slug, desc in all_sensors.items():
            if slug not in self.discovered_sensors:
                self.mqtt.publish_discovery(desc['component'], slug, desc['name'], desc.get('device_class'), desc.get('unit'), desc.get('icon'), None, desc.get('state_class'))
                self.discovered_sensors.add(slug)

        self.mqtt.publish_sensor_state("hottest_cpu_temp", {"temperature": status['hottest_cpu_temp_c']})
        self.mqtt.publish_sensor_state("inlet_temp", {"temperature": status['inlet_temp_c']})
        self.mqtt.publish_sensor_state("exhaust_temp", {"temperature": status['exhaust_temp_c']})
        self.mqtt.publish_sensor_state("power", {"power": status['power_consumption_watts']})
        target_speed_val = status['target_fan_speed_percent']
        self.mqtt.publish_sensor_state("target_fan_speed", {"speed": None if isinstance(target_speed_val, str) else target_speed_val})
        for i, temp in enumerate(status.get('cpu_temps_c', [])):
            self.mqtt.publish_sensor_state(f"cpu_{i}_temp", {"temperature": temp})
        for fan in status.get('actual_fan_rpms', []):
            slug = f"fan_{re.sub(r'[^a-zA-Z0-9_]+', '', fan['name']).lower()}_rpm"
            self.mqtt.publish_sensor_state(slug, {"rpm": fan['rpm']})

    def cleanup(self):
        self._log("info", "Worker shutting down. Reverting to Dell auto fans.")
        self.ipmi.apply_dell_fan_control_profile()
        if self.mqtt.is_connected:
            self.mqtt.disconnect()
        self._log("info", "Worker cleanup complete.")

    def stop(self):
        self.running = False

# --- Main Execution ---
if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Multi-Server Controller Starting =====", flush=True)

    # Explicitly get all expected configuration values from the environment
    global_options = {
        "log_level": os.getenv("LOG_LEVEL", "info"),
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", 60)),
        "master_encryption_key": os.getenv("MASTER_ENCRYPTION_KEY", ""),
        # MQTT settings
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "mqtt_port": int(os.getenv("MQTT_PORT", 1883)),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", ""),
        # Default fan thresholds
        "base_fan_speed_percent": int(os.getenv("BASE_FAN_SPEED_PERCENT", 20)),
        "low_temp_threshold": int(os.getenv("LOW_TEMP_THRESHOLD", 45)),
        "high_temp_fan_speed_percent": int(os.getenv("HIGH_TEMP_FAN_SPEED_PERCENT", 50)),
        "critical_temp_threshold": int(os.getenv("CRITICAL_TEMP_THRESHOLD", 65)),
    }

    SERVERS_CONFIG_FILE = "/data/servers_config.json"
    servers_configs_list = []
    if not os.path.exists(SERVERS_CONFIG_FILE):
        with open(SERVERS_CONFIG_FILE, 'w') as f: json.dump([], f)
    else:
        with open(SERVERS_CONFIG_FILE, 'r') as f:
            try: servers_configs_list = json.load(f)
            except json.JSONDecodeError: pass

    web_server.global_config = global_options
    web_server_port = int(os.getenv("INGRESS_PORT", 8099))
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port, STATUS_FILE, status_lock), daemon=True)
    web_thread.start()

    worker_instances = []
    for server_conf in servers_configs_list:
        if server_conf.get("enabled", False):
            worker = ServerWorker(server_conf, global_options)
            worker_instances.append(worker)
            thread = threading.Thread(target=worker.run, daemon=True)
            threads.append(thread)
            thread.start()

    try:
        while running:
            with status_lock:
                try:
                    with open(STATUS_FILE, 'w') as f: json.dump(list(ALL_SERVERS_STATUS.values()), f, indent=4)
                except IOError as e: print(f"[MAIN] ERROR: Could not write to status file {STATUS_FILE}: {e}", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        graceful_shutdown(None, None)

    print("[MAIN] Waiting for all server threads to terminate...", flush=True)
    for worker in worker_instances: worker.stop()
    for thread in threads: thread.join(timeout=10)
    print("[MAIN] ===== HA iDRAC Controller Stopped =====", flush=True)
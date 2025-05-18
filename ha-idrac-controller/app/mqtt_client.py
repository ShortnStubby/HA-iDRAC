# HA-iDRAC/ha-idrac-controller/app/mqtt_client.py
import paho.mqtt.client as mqtt
import os
import time
import json

# To get server_info for device block in discovery. This is a bit of a circular dependency.
# A better pattern might be to pass the device_info dict to the MqttClient or to discovery methods.
# For now, we'll try to import it, assuming main.py populates it early.
# This can be problematic if mqtt_client is initialized before server_info is ready.
# Let's make publish_sensor_discovery take device_info as an argument.
# from .main import server_info # Avoid this direct cross-import if possible

class MqttClient:
    def __init__(self, client_id="ha_idrac_controller"):
        self.client_id = client_id
        # Use MQTTv311 if v5 causes issues or isn't needed
        self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
        self.broker_address = os.getenv("MQTT_HOST", "core-mosquitto")
        self.port = int(os.getenv("MQTT_PORT", 1883))
        self.username = os.getenv("MQTT_USERNAME", "")
        self.password = os.getenv("MQTT_PASSWORD", "")
        self.is_connected = False
        self.device_info_dict = None # Will be set from main.py

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        if self.username: # Only set if username is provided
             self.client.username_pw_set(self.username, self.password)
    
    def set_device_info(self, manufacturer, model, ip_address):
        """Sets device information for MQTT discovery messages."""
        sanitized_ip = ip_address.replace('.', '_') if ip_address else "default_ip"
        self.device_info_dict = {
            "identifiers": [f"idrac_controller_{sanitized_ip}_device"],
            "name": f"iDRAC Controller ({ip_address or 'N/A'})",
            "model": model or "HA iDRAC Controller",
            "manufacturer": manufacturer or "Aesgarth Add-ons"
        }

    def on_connect(self, client, userdata, flags, rc): # Removed properties for MQTTv311
        if rc == 0:
            print(f"[INFO] MQTT: Connected successfully to broker {self.broker_address}:{self.port}", flush=True)
            self.is_connected = True
            
            # Base availability topic
            status_config_topic = "homeassistant/binary_sensor/ha_idrac_controller/status/config"
            status_config_payload = {
                "name": "iDRAC Controller Status",
                "state_topic": "ha_idrac_controller/status",
                "unique_id": f"idrac_controller_{self.device_info_dict['identifiers'][0] if self.device_info_dict else 'default'}_online_status",
                "device_class": "connectivity",
                "payload_on": "online",
                "payload_off": "offline",
                "device": self.device_info_dict or {} # Add device info
            }
            self.publish(status_config_topic, json.dumps(status_config_payload), retain=True)
            self.publish("ha_idrac_controller/status", "online", retain=True)

            # Publish discovery for sensors
            # CPU Temps (assuming up to 2 for now, can be expanded)
            for i in range(2): # For CPU 0 and CPU 1
                self.publish_sensor_discovery(
                    sensor_type_slug=f"cpu_{i}_temp",
                    sensor_name=f"CPU {i} Temperature",
                    device_class="temperature",
                    unit_of_measurement="°C",
                    value_template="{{ value_json.temperature | round(1) }}"
                )
            # Inlet Temp
            self.publish_sensor_discovery(
                sensor_type_slug="inlet_temp",
                sensor_name="Inlet Temperature",
                device_class="temperature",
                unit_of_measurement="°C",
                value_template="{{ value_json.temperature | round(1) }}"
            )
            # Exhaust Temp
            self.publish_sensor_discovery(
                sensor_type_slug="exhaust_temp",
                sensor_name="Exhaust Temperature",
                device_class="temperature",
                unit_of_measurement="°C",
                value_template="{{ value_json.temperature | round(1) }}"
            )
            # Target Fan Speed
            self.publish_sensor_discovery(
                sensor_type_slug="target_fan_speed",
                sensor_name="Target Fan Speed",
                unit_of_measurement="%",
                icon="mdi:fan",
                value_template="{{ value_json.speed | round(0) }}"
            )
            # TODO: Add discovery for actual fan RPMs (e.g., Fan1_RPM, Fan2_RPM)
            # Example:
            # self.publish_sensor_discovery(
            #     sensor_type_slug="fan_1a_rpm",
            #     sensor_name="Fan 1A RPM",
            #     unit_of_measurement="RPM",
            #     icon="mdi:fan-speed-1", # Or mdi:fan
            #     value_template="{{ value_json.rpm | round(0) }}"
            # )

        else:
            print(f"[ERROR] MQTT: Connection failed with code {rc}", flush=True)
            self.is_connected = False

    def on_disconnect(self, client, userdata, rc): # Removed properties for MQTTv311
        print(f"[INFO] MQTT: Disconnected from broker with result code {rc}.", flush=True)
        self.is_connected = False
        # Note: paho-mqtt's loop_start() handles reconnections automatically.

    def connect(self):
        if not self.is_connected:
            print(f"[INFO] MQTT: Attempting to connect to broker {self.broker_address}:{self.port}...", flush=True)
            try:
                # Set Last Will and Testament (LWT)
                self.client.will_set("ha_idrac_controller/status", payload="offline", qos=1, retain=True)
                self.client.connect(self.broker_address, self.port, 60)
                self.client.loop_start() 
            except ConnectionRefusedError:
                print(f"[ERROR] MQTT: Connection refused by broker {self.broker_address}:{self.port}. Check credentials and broker config.", flush=True)
                self.is_connected = False
            except OSError as e: # Catches [Errno 113] Host is unreachable, etc.
                print(f"[ERROR] MQTT: OS error while connecting to broker {self.broker_address}:{self.port} - {e}", flush=True)
                self.is_connected = False
            except Exception as e:
                print(f"[ERROR] MQTT: Could not connect to broker: {e}", flush=True)
                self.is_connected = False

    def disconnect(self):
        if self.is_connected:
            self.publish("ha_idrac_controller/status", "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
            print("[INFO] MQTT: Gracefully disconnected.", flush=True)

    def publish(self, topic, payload, retain=False, qos=0):
        if self.is_connected:
            try:
                # print(f"[DEBUG] MQTT: Publishing to {topic}: {payload}", flush=True) # Can be very verbose
                msg_info = self.client.publish(topic, payload, qos=qos, retain=retain)
                if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
                    # print(f"[TRACE] MQTT: Message mid {msg_info.mid} enqueued for topic {topic}.", flush=True)
                    pass
                else:
                    print(f"[WARNING] MQTT: Failed to enqueue message for topic {topic}. Error code: {msg_info.rc}", flush=True)
                return msg_info.is_published() # This doesn't guarantee delivery, just enqueued
            except Exception as e:
                print(f"[ERROR] MQTT: Failed to publish to {topic}: {e}", flush=True)
        else:
            print(f"[WARNING] MQTT: Not connected. Cannot publish to {topic}.", flush=True)
        return False

    def publish_sensor_discovery(self, sensor_type_slug, sensor_name, device_class=None, unit_of_measurement=None, icon=None, value_template=None, entity_category=None):
        """Publishes a generic sensor discovery message."""
        if not self.device_info_dict:
            print("[WARNING] MQTT: Device info not set. Cannot publish discovery message for {sensor_name}.", flush=True)
            return

        discovery_topic_slug = f"idrac_{sensor_type_slug}" # e.g., idrac_cpu_0_temp
        config_topic = f"homeassistant/sensor/{discovery_topic_slug}/config"
        
        payload = {
            "name": f"iDRAC {sensor_name}",
            "state_topic": f"ha_idrac_controller/sensor/{discovery_topic_slug}/state",
            "unique_id": f"idrac_controller_{self.device_info_dict['identifiers'][0]}_{sensor_type_slug}",
            "device": self.device_info_dict,
            "availability_topic": "ha_idrac_controller/status",
            "payload_available": "online",
            "payload_not_available": "offline"
        }
        if device_class: payload["device_class"] = device_class
        if unit_of_measurement: payload["unit_of_measurement"] = unit_of_measurement
        if icon: payload["icon"] = icon
        if value_template: payload["value_template"] = value_template
        if entity_category: payload["entity_category"] = entity_category # e.g. "diagnostic"

        self.publish(config_topic, json.dumps(payload), retain=True)
        print(f"[DEBUG] MQTT: Published discovery for {sensor_name} on topic {config_topic}", flush=True)

    def publish_sensor_state(self, sensor_type_slug, value_dict):
        """Publishes state for a sensor, expecting value_dict to contain the keys used in value_template."""
        # Example: value_dict = {"temperature": 25.5} for a temperature sensor
        # Example: value_dict = {"rpm": 3000} for a fan sensor
        # Example: value_dict = {"speed": 50} for target fan speed sensor
        topic_slug = f"idrac_{sensor_type_slug}"
        state_topic = f"ha_idrac_controller/sensor/{topic_slug}/state"
        self.publish(state_topic, json.dumps(value_dict))
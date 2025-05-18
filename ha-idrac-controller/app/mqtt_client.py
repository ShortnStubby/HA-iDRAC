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
        # Note: p
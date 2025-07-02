# HA-iDRAC/ha-idrac-controller-dev/app/mqtt_client.py
import paho.mqtt.client as mqtt
import json
import re

class MqttClient:
    def __init__(self, client_id="ha_idrac_controller"):
        self.client_id = client_id
        self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
        self.broker_address = "core-mosquitto"
        self.port = 1883
        self.username = ""
        self.password = ""
        self.is_connected = False
        self.log_level = "info"
        
        self.base_topic = "ha_idrac_controller"
        self.availability_topic = f"{self.base_topic}/status"
        self.device_info_dict = None

        # *** MISSING LINES ADDED BACK HERE ***
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def _log(self, level, message):
        levels = {"trace": -1, "debug": 0, "info": 1, "warning": 2, "error": 3, "fatal": 4}
        if levels.get(self.log_level, levels["info"]) <= levels.get(level.lower(), levels["info"]):
            print(f"[{level.upper()}] MQTT ({self.client_id}): {message}", flush=True)

    def configure_broker(self, host, port, username, password, log_level="info"):
        self.broker_address = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.log_level = log_level.lower()
        if self.username:
            self.client.username_pw_set(self.username, self.password)

    def set_device_info(self, server_alias, manufacturer, model, ip_address):
        safe_alias = re.sub(r'[^a-zA-Z0-9_-]+', '_', server_alias)
        self.base_topic = f"ha_idrac_controller/{safe_alias}"
        self.availability_topic = f"{self.base_topic}/status"
        self.device_info_dict = {
            "identifiers": [f"idrac_controller_{safe_alias}"],
            "name": f"iDRAC ({server_alias})",
            "model": model or "PowerEdge Server",
            "manufacturer": manufacturer or "DELL",
            "configuration_url": f"http://{ip_address}" if ip_address else None
        }
        self._log("info", f"Device info for MQTT discovery set for '{server_alias}'")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._log("info", f"Connected successfully to broker {self.broker_address}:{self.port}")
            self.is_connected = True
            # Publish online status upon successful connection
            self.publish(self.availability_topic, "online", retain=True)
        else:
            self._log("error", f"Connection failed with code {rc}")
            self.is_connected = False

    def on_disconnect(self, client, userdata, rc):
        self._log("info", f"Disconnected from broker with result code {rc}.")
        self.is_connected = False

    def connect(self):
        if self.is_connected: return
        self._log("info", f"Attempting to connect to broker {self.broker_address}...")
        try:
            # Set Last Will and Testament
            self.client.will_set(self.availability_topic, payload="offline", qos=1, retain=True)
            self.client.connect(self.broker_address, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            self._log("error", f"Could not connect to broker: {e}")

    def disconnect(self):
        if not self.is_connected: return
        # Publish offline status before disconnecting gracefully
        self.publish(self.availability_topic, "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()
        self._log("info", "Gracefully disconnected.")
        self.is_connected = False

    def publish(self, topic, payload, retain=False, qos=0):
        if not self.is_connected:
            self._log("warning", f"Not connected. Cannot publish to {topic}.")
            return
        try:
            self.client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as e:
            self._log("error", f"Failed to publish to {topic}: {e}")

    def publish_discovery(self, component, sensor_type_slug, sensor_name, device_class=None, unit_of_measurement=None, icon=None, value_template=None, state_class=None):
        if not self.device_info_dict:
            self._log("warning", f"Device info not set. Cannot publish discovery for {sensor_name}.")
            return

        unique_id = f"{self.device_info_dict['identifiers'][0]}_{sensor_type_slug}"
        # Correctly format the topic for discovery
        config_topic = f"homeassistant/{component}/{self.device_info_dict['identifiers'][0]}/{sensor_type_slug}/config"
        
        payload = {
            "name": sensor_name,
            "unique_id": unique_id,
            "device": self.device_info_dict,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline"
        }
        
        if component == 'sensor':
             payload["state_topic"] = f"{self.base_topic}/sensor/{sensor_type_slug}/state"
        elif component == 'binary_sensor':
             payload["state_topic"] = self.availability_topic # The connectivity sensor uses the main availability topic
        
        if device_class: payload["device_class"] = device_class
        if unit_of_measurement: payload["unit_of_measurement"] = unit_of_measurement
        if icon: payload["icon"] = icon
        if value_template: payload["value_template"] = value_template
        if state_class: payload["state_class"] = state_class

        self.publish(config_topic, json.dumps(payload), retain=True)
        self._log("debug", f"Published discovery for '{sensor_name}' (unique_id: {unique_id})")

    def publish_sensor_state(self, sensor_type_slug, value_dict):
        if not self.device_info_dict:
            return
        state_topic = f"{self.base_topic}/sensor/{sensor_type_slug}/state"
        self.publish(state_topic, json.dumps(value_dict))
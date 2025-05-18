# HA-iDRAC/ha-idrac-controller/app/mqtt_client.py
import paho.mqtt.client as mqtt
import os
import time
import json

class MqttClient:
    def __init__(self, client_id="ha_idrac_controller"):
        self.client_id = client_id
        self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv5) # Specify MQTTv5 if your broker supports it, or remove for default
        # TODO: Get broker details from HA configuration or add-on options
        # For now, you might hardcode or use defaults if using HA's Mosquitto add-on
        self.broker_address = os.getenv("MQTT_HOST", "core-mosquitto") # Default for HA internal broker
        self.port = int(os.getenv("MQTT_PORT", 1883))
        self.username = os.getenv("MQTT_USERNAME", "") # Often blank for HA internal broker if set up that way
        self.password = os.getenv("MQTT_PASSWORD", "")

        self.is_connected = False

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        # self.client.on_message = self.on_message # If you need to subscribe

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
    
    def on_connect(self, client, userdata, flags, rc, properties=None): # Added properties for MQTTv5
        if rc == 0:
            print(f"[INFO] MQTT: Connected successfully to broker {self.broker_address}:{self.port}")
            self.is_connected = True
            # TODO: Publish availability status
            self.publish("homeassistant/sensor/ha_idrac_controller/status/config", 
                         json.dumps({"name": "iDRAC Controller Status", "state_topic": "ha_idrac_controller/status", "unique_id": "idrac_controller_status_sensor"}), 
                         retain=True)
            self.publish("ha_idrac_controller/status", "online", retain=True)
        else:
            print(f"[ERROR] MQTT: Connection failed with code {rc}")
            self.is_connected = False

    def on_disconnect(self, client, userdata, rc, properties=None): # Added properties for MQTTv5
        print(f"[INFO] MQTT: Disconnected from broker with result code {rc}.")
        self.is_connected = False
        # TODO: Implement reconnection logic if desired

    def connect(self):
        if not self.is_connected:
            print(f"[INFO] MQTT: Attempting to connect to broker {self.broker_address}:{self.port}...")
            try:
                self.client.connect(self.broker_address, self.port, 60)
                self.client.loop_start() # Start a background thread to handle network traffic, reconnections, etc.
            except Exception as e:
                print(f"[ERROR] MQTT: Could not connect to broker: {e}")
                self.is_connected = False

    def disconnect(self):
        if self.is_connected:
            self.publish("ha_idrac_controller/status", "offline", retain=True) # LWT should handle this too if set
            self.client.loop_stop() # Stop the network loop
            self.client.disconnect()
            print("[INFO] MQTT: Disconnected.")

    def publish(self, topic, payload, retain=False, qos=0):
        if self.is_connected:
            try:
                result = self.client.publish(topic, payload, qos=qos, retain=retain)
                # result.wait_for_publish() # Optionally wait for publish confirmation
                print(f"[DEBUG] MQTT: Published to {topic}: {payload}")
                return result.is_published()
            except Exception as e:
                print(f"[ERROR] MQTT: Failed to publish to {topic}: {e}")
        else:
            print(f"[WARNING] MQTT: Not connected. Cannot publish to {topic}.")
        return False

    # TODO: Implement Home Assistant MQTT Discovery messages here
    # Example for a CPU temperature sensor:
    def publish_cpu_temp_discovery(self, cpu_id="1"):
        topic_slug = f"idrac_cpu{cpu_id}_temp"
        config_payload = {
            "name": f"iDRAC CPU {cpu_id} Temperature",
            "state_topic": f"ha_idrac_controller/sensor/{topic_slug}/state",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "value_template": "{{ value_json.temperature | default(0) }}", # If publishing JSON
            # "value_template": "{{ value }}", # If publishing plain value
            "unique_id": f"idrac_cpu{cpu_id}_temp_sensor",
            "device": { # Link this sensor to a device representing the iDRAC controller
                "identifiers": [f"idrac_controller_{os.getenv('IDRAC_IP','default')}_device"],
                "name": f"iDRAC Controller ({os.getenv('IDRAC_IP','default')})",
                "model": "HA iDRAC Controller Add-on", # You can get actual server model later
                "manufacturer": "Aesgarth Add-ons"
            },
            "availability_topic": "ha_idrac_controller/status",
            "payload_available": "online",
            "payload_not_available": "offline"
        }
        self.publish(f"homeassistant/sensor/{topic_slug}/config", json.dumps(config_payload), retain=True)

    def publish_temperature(self, sensor_name="cpu1_temp", temperature_value=None):
        if temperature_value is not None:
            # If you used value_template with json:
            # self.publish(f"ha_idrac_controller/sensor/{sensor_name}/state", json.dumps({"temperature": temperature_value}))
            # If you used plain value:
            self.publish(f"ha_idrac_controller/sensor/{sensor_name}/state", str(temperature_value))

# Example usage (would be in main.py)
# if __name__ == '__main__':
#     mqtt_client = MqttClient()
#     mqtt_client.connect()
#     time.sleep(2) # Give time to connect
#     if mqtt_client.is_connected:
#         mqtt_client.publish_cpu_temp_discovery()
#         mqtt_client.publish_temperature("idrac_cpu1_temp", 35.5)
#         time.sleep(60)
#         mqtt_client.disconnect()
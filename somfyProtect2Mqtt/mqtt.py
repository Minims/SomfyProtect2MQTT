"""MQTT"""
import logging
import json
import paho.mqtt.client as mqtt
from time import sleep

LOGGER = logging.getLogger(__name__)

from ha_discovery import ALARM_STATUS
from somfy_protect_api.api.somfy_protect_api import ACTION_LIST


class MQTTClient:
    """MQTT Client Class"""

    def __init__(self, config, api, publish_delay=1):
        self.publish_delay = publish_delay

        self.api = api

        self.client = mqtt.Client(client_id=config.get("client-id", "somfy-protect"))
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_disconnect = self.on_disconnect
        self.client.username_pw_set(config.get("username"), config.get("password"))
        self.client.connect(config.get("host", "127.0.0.1"), config.get("port", 1883), 60)
        self.client.loop_start()

        self.config = config
        self.running = True

        LOGGER.debug("MQTT client initialized")

    def on_connect(self, mqttc, obj, flags, rc):
        """MQTT on_connect"""
        LOGGER.debug(f"Connected: {rc}")

    def on_message(self, mqttc, obj, msg):
        """MQTT on_message"""
        LOGGER.debug(f"Message received on {msg.topic}: {msg.payload}")
        try:
            text_payload = msg.payload.decode("UTF-8")
            if text_payload in ALARM_STATUS.keys():
                LOGGER.info(f"Security Level update ! Setting to {text_payload}")
                try:
                    site_id = msg.topic.split("/")[1]
                    LOGGER.debug(f"Site ID: {site_id}")
                except Exception as exp:
                    LOGGER.warning(f"Unable to reteive Site ID")
                self.api.update_security_level(site_id=site_id, security_level=text_payload)
                # Re Read site
                self.update_site(site_id=site_id)
            elif text_payload == "panic":
                site_id = msg.topic.split("/")[1]
                LOGGER.info(f"Start the Siren On Site ID {site_id}")
                self.api.trigger_alarm(site_id=site_id, mode="alarm")
            elif text_payload == "stop":
                site_id = msg.topic.split("/")[1]
                LOGGER.info(f"Stop the Siren On Site ID {site_id}")
                self.api.stop_alarm(site_id=site_id)
            elif msg.topic.split("/")[3] == "shutter_state":
                site_id = msg.topic.split("/")[1]
                device_id = msg.topic.split("/")[2]
                if text_payload == "closed":
                    text_payload = "shutter_close"
                if text_payload == "opened":
                    text_payload = "shutter_open"
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Action: {text_payload}")
                action_device = self.api.action_device(
                    site_id=site_id,
                    device_id=device_id,
                    action=text_payload,
                )
                LOGGER.debug(action_device)
                # Re Read device
                sleep(3)
                self.update_device(site_id=site_id, device_id=device_id)
            elif msg.topic.split("/")[3] == "snapshot":
                site_id = msg.topic.split("/")[1]
                device_id = msg.topic.split("/")[2]
                if text_payload == "True":
                    LOGGER.info("Manual Snapshot")
                    self.api.camera_refresh_snapshot(site_id=site_id, device_id=device_id)
                    response = self.api.camera_snapshot(site_id=site_id, device_id=device_id)
                    if response.status_code == 200:
                        # Write image to temp file
                        path = f"{device_id}.jpeg"
                        with open(path, "wb") as f:
                            for chunk in response:
                                f.write(chunk)
                        # Read and Push to MQTT
                        f = open(path, "rb")
                        image = f.read()
                        byteArr = bytearray(image)
                        topic = f"{self.config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                        self.update(topic, byteArr, retain=False, is_json=False)
            else:
                site_id = msg.topic.split("/")[1]
                device_id = msg.topic.split("/")[2]
                setting = msg.topic.split("/")[3]
                device = self.api.get_device(site_id=site_id, device_id=device_id)
                LOGGER.info(f"Message received for Site ID: {site_id}, Device ID: {device_id}, Setting: {setting}")
                settings = device.settings
                settings["global"][setting] = text_payload
                update_device = self.api.update_device(
                    site_id=site_id,
                    device_id=device_id,
                    device_label=device.label,
                    settings=settings,
                )
                LOGGER.debug(update_device)
                # Re Read device
                sleep(3)
                self.update_device(site_id=site_id, device_id=device_id)
        except Exception as exp:
            LOGGER.error(f"Error when processing message: {exp}")

    def on_publish(self, mqttc, obj, result):
        """MQTT on_publish"""
        LOGGER.debug(f"Message published: {result}")

    def update(self, topic, payload, qos=0, retain=False, is_json=True):
        """MQTT update"""
        try:
            if is_json:
                self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            else:
                self.client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as exp:
            LOGGER.error(f"Error when publishing message: {exp}")

    def run(self):
        """MQTT run"""
        LOGGER.info("RUN")

    def shutdown(self):
        """MQTT shutdown"""
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()

    def update_device(self, site_id, device_id):
        LOGGER.info(f"Live Update device {device_id}")
        try:
            device = self.api.get_device(site_id=site_id, device_id=device_id)
            settings = device.settings.get("global")
            status = device.status
            status_settings = {**status, **settings}

            # Convert Values to String
            keys_values = status_settings.items()
            payload = {str(key): str(value) for key, value in keys_values}
            # Push status to MQTT
            self.update(
                topic=f"{self.config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
                payload=payload,
                retain=False,
            )
        except Exception as exp:
            LOGGER.warning(f"Error while refreshing {device.label}: {exp}")

    def update_site(self, site_id):
        LOGGER.info(f"Live Update site {site_id}")
        try:
            site = self.api.get_site(site_id=site_id)
            # Push status to MQTT
            self.update(
                topic=f"{self.config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
                payload={"security_level": ALARM_STATUS.get(site.security_level, "disarmed")},
                retain=False,
            )
        except Exception as exp:
            LOGGER.warning(f"Error while refreshing site {site_id}: {exp}")

    def on_disconnect(self, userdata, rc, properties=None):
        if rc != 0:
            LOGGER.warning("Unexpected MQTT disconnection. Will auto-reconnect")
            try:
                LOGGER.info("Reconnecting to MQTT")
                self.client.reconnect()
            except ConnectionRefusedError:
                LOGGER.warning("Reconnecting to MQTT fails")
                sleep(10)
                self.on_disconnect
            LOGGER.info("Reconnecting to MQTT: Success")

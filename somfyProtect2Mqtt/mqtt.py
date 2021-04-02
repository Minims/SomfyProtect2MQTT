"""MQTT"""
import logging
import json
import paho.mqtt.client as mqtt

LOGGER = logging.getLogger(__name__)

AVAILABLE_STATUS = ["partial", "armed", "disarmed"]


class MQTTClient:
    """MQTT Client Class
    """

    def __init__(self, config, api, publish_delay=1):
        self.publish_delay = publish_delay

        self.api = api

        self.client = mqtt.Client(client_id=config.get("client-id", "somfy-protect"))
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.username_pw_set(config.get("username"), config.get("password"))
        self.client.connect(
            config.get("host", "127.0.0.1"), config.get("port", 1883), 60
        )
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
            if text_payload in AVAILABLE_STATUS:
                LOGGER.info(f"Security Level update ! Setting to {text_payload}")
                try:
                    site_id = msg.topic.split("/")[1]
                    LOGGER.debug(f"Site ID: {site_id}")
                except Exception as exp:
                    LOGGER.warning(f"Unable to reteive Site ID")
                self.api.update_site(site_id=site_id, security_level=text_payload)
        except Exception as exp:
            LOGGER.error(f"Error when processing message: {exp}")

    def on_publish(self, mqttc, obj, result):
        """MQTT on_publish"""
        LOGGER.debug(f"Message published: {result}")

    def update(self, topic, payload, qos=0, retain=False):
        """MQTT update"""
        try:
            self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
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

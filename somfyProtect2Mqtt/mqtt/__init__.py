"""MQTT"""

import json
import logging
import ssl
from time import sleep

import paho.mqtt.client as mqtt
from business.mqtt import consume_mqtt_message, SUBSCRIBE_TOPICS
from exceptions import SomfyProtectInitError
from homeassistant.ha_discovery import ALARM_STATUS
from somfy_protect.api import SomfyProtectApi

LOGGER = logging.getLogger(__name__)


class MQTTClient:
    """MQTT Client Class"""

    def __init__(self, config, api, publish_delay=1):
        self.publish_delay = publish_delay

        self.client = mqtt.Client(client_id=config.get("client-id", "somfy-protect"))
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        self.client.on_disconnect = self.on_disconnect
        self.client.username_pw_set(config.get("username"), config.get("password"))
        self.client.connect(config.get("host", "127.0.0.1"), config.get("port", 1883), 60)
        if config.get("ssl", False) is True:
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)
        self.client.loop_start()

        self.config = config
        self.running = True
        self.api = api

        LOGGER.debug("MQTT client initialized")

    def on_connect(self, mqttc, obj, flags, rc):  # pylint: disable=unused-argument,invalid-name
        """MQTT on_connect"""
        if rc == 0:
            LOGGER.info(f"Connected: {rc}")
            for topic in SUBSCRIBE_TOPICS:
                LOGGER.info(f"Subscribing to: {topic}")
                self.client.subscribe(topic)
        else:
            LOGGER.info(f"Not Connected: {rc}")

    def on_message(self, mqttc, obj, msg):  # pylint: disable=unused-argument
        """MQTT on_message"""
        LOGGER.debug(f"Message received on {msg.topic}: {msg.payload}")
        consume_mqtt_message(
            msg=msg,
            mqtt_config=self.config,
            api=self.api,
            mqtt_client=self,
        )

    def on_publish(self, mqttc, obj, result):  # pylint: disable=unused-argument
        """MQTT on_publish"""
        LOGGER.debug(f"Message published: {result}")

    def on_disconnect(self, userdata, rc, properties=None):  # pylint: disable=unused-argument,invalid-name
        """MQTT on_disconnect"""
        if rc != 0:
            LOGGER.warning("Unexpected MQTT disconnection. Will auto-reconnect")
            try:
                LOGGER.info("Reconnecting to MQTT")
                self.client.reconnect()
                LOGGER.info("Reconnecting to MQTT: Success")
            except ConnectionRefusedError:
                LOGGER.warning("Reconnecting to MQTT failed, will retry...")
                sleep(10)
                try:
                    self.client.reconnect()
                except Exception as e:
                    LOGGER.error(f"Second reconnect attempt failed: {e}")

    def run(self):
        """MQTT run"""
        LOGGER.info("RUN")

    def shutdown(self):
        """MQTT shutdown"""
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()


def init_mqtt(config: dict, api: SomfyProtectApi) -> MQTTClient:
    """Init MQTT

    Args:
        config (dict): Global Configuration

    Raises:
        SomfyProtectInitError: Unable to init
    """
    logging.info("Init MQTT")
    mqtt_config = config.get("mqtt")
    if mqtt_config is None:
        raise SomfyProtectInitError("MQTT config is missing")
    mqtt_client = MQTTClient(config=mqtt_config, api=api)
    return mqtt_client

"""MQTT"""

import json
import logging
import ssl
from time import sleep

import paho.mqtt.client as mqtt
from business.mqtt import SUBSCRIBE_TOPICS, consume_mqtt_message
from exceptions import SomfyProtectInitError
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
        if config.get("ssl", False) is True:
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)
        self.client.connect(config.get("host", "127.0.0.1"), config.get("port", 1883), 60)
        self.client.loop_start()

        self.config = config
        self.running = True
        self.api = api

        LOGGER.debug("MQTT client initialized")

    def on_connect(self, _mqttc, _obj, _flags, rc):
        """MQTT on_connect"""
        if rc == 0:
            LOGGER.info("Connected: {}".format(rc))
            for topic in sorted(SUBSCRIBE_TOPICS):
                LOGGER.info("Subscribing to: {}".format(topic))
                self.client.subscribe(topic)
        else:
            LOGGER.info("Not Connected: {}".format(rc))

    def on_message(self, _mqttc, _obj, msg):
        """MQTT on_message"""
        LOGGER.debug("Message received on {}: {}".format(msg.topic, msg.payload))
        consume_mqtt_message(
            msg=msg,
            mqtt_config=self.config,
            api=self.api,
            mqtt_client=self,
        )

    def on_publish(self, _mqttc, _obj, result):
        """MQTT on_publish"""
        LOGGER.debug("Message published: {}".format(result))

    def on_disconnect(self, _userdata, rc, _properties=None):
        """MQTT on_disconnect"""
        if rc != 0:
            LOGGER.warning("Unexpected MQTT disconnection. Will auto-reconnect")
            backoff = 5
            while self.running:
                try:
                    LOGGER.info("Reconnecting to MQTT")
                    self.client.reconnect()
                    LOGGER.info("Reconnecting to MQTT: Success")
                    break
                except ConnectionRefusedError:
                    LOGGER.warning("Reconnecting to MQTT fails")
                    sleep(backoff)
                    backoff = min(backoff * 2, 60)

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

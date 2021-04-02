"""Somfy Protect 2 Mqtt"""
import logging
from time import sleep

from exceptions import SomfyProtectInitError
import schedule
from mqtt import MQTTClient
from somfy_protect import init_somfy_protect
from somfy_protect_api.api.devices.category import Category
from somfy_protect_api.api.devices.outdoor_siren import OutDoorSiren
from ha_discovery import (
    ha_discovery_alarm,
    ha_discovery_devices,
    DEVICE_CAPABILITIES,
    ALARM_STATUS,
)

LOGGER = logging.getLogger(__name__)


class SomfyProtect2Mqtt:
    """SomfyProtect2Mqtt Class

    Raises:
        SomfyProtectInitError: Unable to init
    """

    def __init__(self, config: dict) -> None:
        """Init SomfyProtect2Mqtt

        Args:
            config (dict): Global Configuration
            lock (Event, optional): [description]. Defaults to None.

        Raises:
            SomfyProtectInitError: Unable to init
        """
        logging.info("Init SomfyProtect2Mqtt")
        username = config.get("somfy_protect").get("username")
        password = config.get("somfy_protect").get("password")
        if username is None or password is None:
            raise SomfyProtectInitError

        my_sites = config.get("somfy_protect").get("sites")

        self.delay_site = config.get("delay_site", 60)
        self.delay_device = config.get("delay_device", 60)

        if self.delay_site < 10:
            self.delay_site = 10
        if self.delay_device < 10:
            self.delay_device = 10

        self.somfy_protect_api = init_somfy_protect(
            username=username, password=password
        )
        self.my_sites = my_sites
        self.my_sites_id = []

        mqtt_config = config.get("mqtt")
        self.mqtt_config = mqtt_config
        if mqtt_config is None:
            raise SomfyProtectInitError
        self.mqttc = MQTTClient(config=mqtt_config, api=self.somfy_protect_api)
        sites = self.somfy_protect_api.get_sites()
        LOGGER.info(f"Found {len(sites)} Site(s)")
        for site in sites:
            if site.label in self.my_sites:
                LOGGER.info(f"Storing Site ID for {site.label}")
                self.my_sites_id.append(site.id)

    def close(self) -> None:
        """Close
        """
        return

    def loop(self) -> None:
        """Main Loop
        """
        self.ha_sites_config()
        self.ha_devices_config()
        self.update_sites_status()
        self.update_devices_status()
        schedule.every(self.delay_site).seconds.do(self.update_sites_status)
        schedule.every(self.delay_device).seconds.do(self.update_devices_status)

        while True:
            schedule.run_pending()

    def ha_sites_config(self) -> None:
        """HA Site Config
        """
        LOGGER.info(f"Look for Sites")
        for site_id in self.my_sites_id:
            # Alarm Status
            my_site = self.somfy_protect_api.get_site(site_id=site_id)
            site_config = ha_discovery_alarm(site=my_site, mqtt_config=self.mqtt_config)
            self.mqttc.update(
                topic=site_config.get("topic"),
                payload=site_config.get("config"),
                retain=True,
            )
            self.mqttc.client.subscribe(site_config.get("config").get("command_topic"))

    def ha_devices_config(self) -> None:
        """HA Devices Config
        """
        LOGGER.info(f"Look for Devices")
        for site_id in self.my_sites_id:
            my_devices = self.somfy_protect_api.get_devices(site_id=site_id)
            for device in my_devices:
                settings = device.settings.get("global")
                status = device.status
                status_settings = {**status, **settings}

                for state in status_settings:
                    if not DEVICE_CAPABILITIES.get(state):
                        LOGGER.debug(f"No Config for {state}")
                        continue
                    device_config = ha_discovery_devices(
                        site_id=site_id,
                        device=device,
                        mqtt_config=self.mqtt_config,
                        sensor_name=state,
                    )
                    self.mqttc.update(
                        topic=device_config.get("topic"),
                        payload=device_config.get("config"),
                        retain=True,
                    )
                    if device_config.get("config").get("command_topic"):
                        self.mqttc.client.subscribe(
                            device_config.get("config").get("command_topic")
                        )

    def update_sites_status(self) -> None:
        """Uodate Devices Status (Including zone)
        """
        LOGGER.info(f"Update Sites Status")
        for site_id in self.my_sites_id:
            try:
                my_sites = self.somfy_protect_api.get_sites()
                for site in my_sites:
                    # Push status to MQTT
                    self.mqttc.update(
                        topic=f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state",
                        payload={
                            "security_level": ALARM_STATUS.get(
                                site.security_level, "disarmed"
                            )
                        },
                    )
            except Exception as exp:
                LOGGER.warning(f"Error while refreshing site: {exp}")
                continue

    def update_devices_status(self) -> None:
        """Uodate Devices Status (Including zone)
        """
        LOGGER.info(f"Update Devices Status")
        for site_id in self.my_sites_id:
            try:
                my_devices = self.somfy_protect_api.get_devices(site_id=site_id)
                for device in my_devices:
                    settings = device.settings.get("global")
                    status = device.status
                    status_settings = {**status, **settings}

                    # Convert Values to String
                    keys_values = status_settings.items()
                    payload = {str(key): str(value) for key, value in keys_values}

                    # Push status to MQTT
                    self.mqttc.update(
                        topic=f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device.id}/state",
                        payload=payload,
                    )
            except Exception as exp:
                LOGGER.warning(f"Error while refreshing devices: {exp}")
                continue

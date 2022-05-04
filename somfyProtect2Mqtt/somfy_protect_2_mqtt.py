"""Somfy Protect 2 Mqtt"""
import logging
from time import sleep

from exceptions import SomfyProtectInitError
import schedule
from somfy_protect.api import SomfyProtectApi
from business import (
    update_camera_snapshot,
    update_devices_status,
    update_sites_status,
    ha_devices_config,
    ha_sites_config,
)
from mqtt import MQTTClient

LOGGER = logging.getLogger(__name__)


class SomfyProtect2Mqtt:
    """SomfyProtect2Mqtt Class

    Raises:
        SomfyProtectInitError: Unable to init
    """

    def __init__(
        self, api: SomfyProtectApi, mqtt_client: MQTTClient, config: dict
    ) -> None:
        """Init SomfyProtect2Mqtt

        Args:
            api (SomfyProtectApi): SomfyProtectApi
            mqtt_client (MQTTClient): MQTTClient
            config (dict): Global Configuration

        Raises:
            SomfyProtectInitError: Unable to init
        """
        logging.info("Init SomfyProtect2Mqtt")

        self.my_sites = config.get("somfy_protect").get("sites")
        self.my_sites_id = []

        self.delay_site = config.get("delay_site", 60)
        self.delay_site = max(self.delay_site, 10)

        self.delay_device = config.get("delay_device", 60)
        self.delay_device = max(self.delay_device, 10)

        self.manual_snapshot = config.get("manual_snapshot", False)

        self.api = api
        self.mqtt_client = mqtt_client

        self.homeassistant_config = config.get("homeassistant_config")

        self.mqtt_config = config.get("mqtt")
        if self.mqtt_config is None:
            raise SomfyProtectInitError

        sites = self.api.get_sites()
        LOGGER.info(f"Found {len(sites)} Site(s)")
        for site in sites:
            if site.label in self.my_sites:
                LOGGER.info(f"Storing Site ID for {site.label}")
                self.my_sites_id.append(site.id)

    def close(self) -> None:  # pylint: disable=no-self-use
        """Close"""
        return

    def loop(self) -> None:
        """Main Loop"""
        # Config
        ha_sites_config(
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
            homeassistant_config=self.homeassistant_config,
        )
        ha_devices_config(
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
        )

        # Device Update (First Run Only)
        update_sites_status(
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
        )
        if not self.manual_snapshot:
            update_camera_snapshot(
                api=self.api,
                mqtt_client=self.mqtt_client,
                mqtt_config=self.mqtt_config,
                my_sites_id=self.my_sites_id,
            )
        update_devices_status(
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
        )

        # Schedule Refreshs
        schedule.every(self.delay_site).seconds.do(
            update_sites_status,
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
        )
        schedule.every(self.delay_device).seconds.do(
            update_devices_status,
            api=self.api,
            mqtt_client=self.mqtt_client,
            mqtt_config=self.mqtt_config,
            my_sites_id=self.my_sites_id,
        )
        if not self.manual_snapshot:
            schedule.every(self.delay_device).seconds.do(
                update_camera_snapshot,
                api=self.api,
                mqtt_client=self.mqtt_client,
                mqtt_config=self.mqtt_config,
                my_sites_id=self.my_sites_id,
            )

        while True:
            schedule.run_pending()
            sleep(10)

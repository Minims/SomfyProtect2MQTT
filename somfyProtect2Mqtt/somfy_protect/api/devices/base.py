"""Device management."""

from typing import Optional, Union, cast

from somfy_protect.api import SomfyProtectApi
from somfy_protect.api.model import Device, Site


class SomfyProtectDevice:
    """Somfy Protect Device"""

    __slots__ = "site", "device", "api"

    def __init__(self, site: Site, device: Device, api: SomfyProtectApi):
        self.site = site
        self.device = device
        self.api = api

    def refresh_state(self) -> None:
        """Refresh State"""
        self.device = self.api.get_device(site_id=self.site.id, device_id=self.device.id)

    def get_version(self) -> str:
        """Get HW/FW Version"""
        return self.device.version

    def get_video_backend(self) -> Optional[str]:
        """Get Video Backend"""
        return self.device.video_backend

    def get_status(self, status_name: str) -> Optional[Union[str, int, float]]:
        """Get a Status for the current device.

        Args:
            status_name (str): Name of status

        Returns:
            Union[str, int, float]: Status value
        """
        if not status_name:
            return None
        return self.device.status.get(status_name)

    def get_setting(self, setting_name: str) -> Optional[Union[str, int, float]]:
        """Get a Setting for the current device.

        Args:
            setting_name (str): Name of setting

        Returns:
            Optional[Union[str, int, float]]: Setting value.
        """
        if not setting_name:
            return None
        return self.device.settings.get(setting_name)


class CameraDevice(SomfyProtectDevice):
    """Common camera device behavior."""

    def get_wifi_level_percent(self) -> float:
        """Link quality in percent.

        Returns:
            float: Link quality percentage.
        """
        return cast(float, self.get_status("wifi_level_percent"))

    def get_shutter_state(self) -> str:
        """Shutter state.

        Returns:
            str: Shutter state (opened or closed).
        """
        return cast(str, self.get_status("shutter_state"))

    def get_power_state(self) -> int:
        """Power state.

        Returns:
            int: Power state (0 or 1).
        """
        return cast(int, self.get_status("power_state"))

    def close_shutter(self) -> None:
        """Close the shutter."""
        self.api.action_device(
            site_id=self.site.id,
            device_id=self.device.id,
            action="shutter_close",
        )

    def open_shutter(self) -> None:
        """Open the shutter."""
        self.api.action_device(
            site_id=self.site.id,
            device_id=self.device.id,
            action="shutter_open",
        )

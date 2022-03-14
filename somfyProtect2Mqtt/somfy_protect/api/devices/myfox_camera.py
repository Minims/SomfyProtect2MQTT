"""Security MyFox Camera"""
from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class MyFoxCamera(SomfyProtectDevice):
    """Class to represent an MyFox Camera."""

    def get_wifi_level_percent(self) -> float:
        """Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("wifi_level_percent"))

    def get_shutter_state(self) -> str:
        """Shutter State

        Returns:
            float: Shutter State (opened and closed)
        """
        return cast(str, self.get_status("shutter_state"))

    def get_power_state(self) -> int:
        """Power State

        Returns:
            float: Power State (0 and 1)
        """
        return cast(int, self.get_status("power_state"))

    def close_shutter(self) -> None:
        """Close Shutter"""
        self.api.action_device(
            site_id=self.site.id,
            device_id=self.device.id,
            action="shutter_close",
        )

    def open_shutter(self) -> None:
        """Open Shutter"""
        self.api.action_device(
            site_id=self.site.id,
            device_id=self.device.id,
            action="shutter_open",
        )

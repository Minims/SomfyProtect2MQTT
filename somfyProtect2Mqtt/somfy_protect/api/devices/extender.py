"""Security Extender"""
from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class Extender(SomfyProtectDevice):
    """Class to represent an Extender."""

    def get_power_mode(self) -> str:
        """Power Mode

        Returns:
            float: Power State (current or ?)
        """
        return cast(str, self.get_status("power_mode"))

    def get_battery_level(self) -> float:
        """Battery Level

        Returns:
            float: Battery Level percentage
        """
        return cast(float, self.get_status("battery_level"))

    def get_rlink_quality(self) -> float:
        """Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("rlink_quality_percent"))

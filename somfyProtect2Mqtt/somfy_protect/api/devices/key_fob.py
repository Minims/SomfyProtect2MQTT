"""Security Key Fob"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class KeyFob(SomfyProtectDevice):
    """Class to represent a Key Fob."""

    def get_rlink_quality(self) -> float:
        """Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("rlink_quality_percent"))

    def get_battery_level(self) -> float:
        """Battery Level

        Returns:
            float: Battery Level percentage
        """
        return cast(float, self.get_status("battery_level"))

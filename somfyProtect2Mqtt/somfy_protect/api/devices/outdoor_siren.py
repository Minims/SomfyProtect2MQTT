"""Security Outdoor Siren"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class OutDoorSiren(SomfyProtectDevice):
    """Class to represent an OutDoor Siren."""

    def get_temperature(self) -> float:
        """Exterior Temperature

        Returns:
            float: Temperature in °C
        """
        return cast(float, self.get_status("temperature"))

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

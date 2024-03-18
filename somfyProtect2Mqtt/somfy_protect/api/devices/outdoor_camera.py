"""Security OutDoor Camera"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class OutDoorCamera(SomfyProtectDevice):
    """Class to represent an OutDoor Camera."""

    def get_wifi_level_percent(self) -> float:
        """Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("wifi_level_percent"))

    def get_power_state(self) -> int:
        """Power State

        Returns:
            float: Power State (0 and 1)
        """
        return cast(int, self.get_status("power_state"))

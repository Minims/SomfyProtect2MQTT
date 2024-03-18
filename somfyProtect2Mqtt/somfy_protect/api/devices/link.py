"""Security Link"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class Link(SomfyProtectDevice):
    """Class to represent an Link."""

    def get_wifi_level_percent(self) -> float:
        """WIFI Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("wifi_level_percent"))

    def get_lora_quality_percent(self) -> float:
        """LORA Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("lora_quality_percent"))

    def get_mfa_quality_percent(self) -> float:
        """MFA Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("mfa_quality_percent"))

    def get_power_state(self) -> int:
        """Power State

        Returns:
            float: Power State (0 or 1)
        """
        return cast(int, self.get_status("power_state"))

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

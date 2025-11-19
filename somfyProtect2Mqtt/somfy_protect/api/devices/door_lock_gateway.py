"""Security IntelliTag"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class DoorLockGateway(SomfyProtectDevice):
    """Class to represent an IntelliTag."""

    def get_wifi_level_percent(self) -> float:
        """WIFI Link Quality in %

        Returns:
            float: Link Quality percentage
        """
        return cast(float, self.get_status("wifi_level_percent"))


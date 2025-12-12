"""Security IntelliTag"""

from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class DoorLock(SomfyProtectDevice):
    """Class to represent an IntelliTag."""

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

    def get_battery_low(self) -> bool:
        """Battery Low

        Returns:
            bool: Battery Low status
        """
        return cast(bool, self.get_status("battery_low"))

    def is_sensor_tof_activated(self) -> bool:
        """Sensor ToF Activated

        Returns:
            bool: Sensor ToF Activated status
        """
        return cast(bool, self.get_status("is_sensor_tof_activated"))

    def door_state(self) -> str:
        """Door State

        Returns:
            str: Door State
        """
        return cast(str, self.get_status("door_state"))

    def door_lock_state(self) -> str:
        """Door Lock State

        Returns:
            str: Door Lock State
        """
        return cast(str, self.get_status("door_lock_state"))

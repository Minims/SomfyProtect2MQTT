"""Security IntelliTag"""
from typing import cast

from somfy_protect.api.devices.base import SomfyProtectDevice


class IntelliTag(SomfyProtectDevice):
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

    def is_cover_present(self) -> bool:
        """Cover Present

        Returns:
            bool: Cover is Present
        """
        return cast(bool, self.get_status("cover_present"))

    def is_recalibration_required(self) -> bool:
        """Is a Recalibration is needed

        Returns:
            bool: Recalibration Needed
        """
        return cast(bool, self.get_status("recalibration_required"))

    def is_recalibrateable(self) -> bool:
        """Is Recalibrateable

        Returns:
            bool: Recalibrateable
        """
        return cast(bool, self.get_status("recalibrateable"))

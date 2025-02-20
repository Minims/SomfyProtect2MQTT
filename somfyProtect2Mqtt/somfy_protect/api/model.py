"""Models Definition"""

from enum import Enum
from typing import Any, Dict, List


class Site:
    """Site Object"""

    __slots__ = (
        "id",
        "label",
        "security_level",
        "diagnosis_status",
        "alarm",
        "services",
    )

    def __init__(
        self,
        site_id: str,
        label: str,
        security_level: str,
        diagnosis_status: str,
        alarm: List,
        services: Dict,
        **_: Any,
    ):
        self.id = site_id  # pylint: disable=invalid-name
        self.label = label
        self.security_level = security_level
        self.diagnosis_status = diagnosis_status
        self.alarm = alarm
        self.services = services


class Device:
    """Device Object"""

    __slots__ = (
        "id",
        "site_id",
        "box_id",
        "label",
        "version",
        "device_definition",
        "status",
        "diagnosis",
        "settings",
        "update_available",
        "video_backend",
    )

    def __init__(
        self,
        device_id: str,
        site_id: str,
        box_id: str,
        label: str,
        version: str,
        device_definition: Dict,
        status: Dict,
        diagnosis: Dict,
        settings: Dict,
        update_available: str = "False",
        video_backend: str = None,
        **_: Any,
    ):
        self.id = device_id  # pylint: disable=invalid-name
        self.site_id = site_id
        self.box_id = box_id
        self.label = label
        self.version = version
        self.device_definition = device_definition
        self.status = status
        self.diagnosis = diagnosis
        self.settings = settings
        self.update_available = update_available
        self.video_backend = video_backend


class AvailableStatus(Enum):
    """List of Allowed Security Level
    Args:
        Enum (str): Security Level
    """

    DISARMED = 1
    ARMED = 2
    PARTIAL = 3


class Status:
    """Alarm Status"""

    def __init__(self, security_level: AvailableStatus):
        self.security_level = security_level


class User:
    """User Object"""

    __slots__ = (
        "id",
        "display_name",
        "display_my_presence",
        "present",
        "activated",
        "geoFence",
    )

    def __init__(
        self,
        user_id: str,
        display_name: str,
        display_my_presence: str,
        present: str,
        activated: str,
        geo_fence: Dict,
        **_: Any,
    ):
        self.id = user_id  # pylint: disable=invalid-name
        self.display_name = display_name
        self.display_my_presence = display_my_presence
        self.present = present
        self.activated = activated
        self.geoFence = geo_fence

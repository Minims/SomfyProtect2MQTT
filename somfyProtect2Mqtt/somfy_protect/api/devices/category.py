"""Devices Categories"""
from aenum import Enum, unique


@unique
class Category(Enum):
    """List of Known Devices"""

    LINK = "Link"
    INDOOR_CAMERA = "Somfy Indoor Camera"
    MYFOX_CAMERA = "Myfox security camera"
    INDOOR_SIREN = "Myfox Security Siren"
    OUTDDOR_CAMERA = "Somfy Outdoor Camera"
    OUTDOOR_SIREN = "Myfox Security Outdoor Siren"
    INTELLITAG = "IntelliTag"
    KEY_FOB = "Key Fob"
    MOTION = "Myfox Security Infrared Sensor"
    SMOKE_DETECTOR = "Somfy Smoke Detector"
    EXTENDER = "Myfox Security Extender"

    @classmethod
    def _missing_name_(cls, name):
        for member in cls:
            if member.name.lower() == name.lower():
                return member

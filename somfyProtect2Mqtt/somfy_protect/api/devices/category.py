"""Devices Categories"""

from aenum import Enum


class Category(Enum):
    """List of Known Devices"""

    LINK = "Link"
    INDOOR_CAMERA = "Somfy Indoor Camera"
    VIDEOPHONE = "Connected Videophone"
    MYFOX_CAMERA = "Myfox security camera"
    INDOOR_SIREN = "Myfox Security Siren"
    OUTDOOR_CAMERA = "Somfy Outdoor Camera"
    OUTDDOR_CAMERA = OUTDOOR_CAMERA
    OUTDOOR_SIREN = "Myfox Security Outdoor Siren"
    INTELLITAG = "IntelliTag"
    KEY_FOB = "Key Fob"
    MOTION = "Myfox Security Infrared Sensor"
    SMOKE_DETECTOR = "Somfy Smoke Detector"
    EXTENDER = "Myfox Security Extender"
    SOMFY_ONE_PLUS = "Somfy One Plus"
    SOMFY_ONE = "Somfy One"

    @classmethod
    def _missing_name_(cls, name):
        for member in cls:
            if member.name.lower() == name.lower():
                return member
        return None

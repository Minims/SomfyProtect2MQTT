"""Somfy Protect Api"""

import base64
import logging
import json
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional, Union

from oauthlib.oauth2 import TokenExpiredError
from requests import Response
from requests_oauthlib import OAuth2Session

from somfy_protect.api.devices.category import Category
from somfy_protect.api.model import AvailableStatus, Device, Site, User

from somfy_protect.sso import SomfyProtectSso, read_token_from_file

LOGGER = logging.getLogger(__name__)


BASE_URL = "https://api.myfox.io"
# Don't know how it works for now.
VIDEO_URL = "https://video.myfox.io"
# (MEDIA_TYPE_VIDEO, 1, 1; MEDIA_TYPE_AUDIO, 0, 0)

ACCESS_LIST = ["gate", "latch", "lock", "unlock", "force_lock"]

ACTION_LIST = [
    "shutter_open",
    "shutter_close",
    "autoprotection_pause",
    "battery_changed",
    "change_video_backend",
    "checkin",
    "checkout",
    "firmware_update_start",
    "range_test_start",
    "range_test_stop",
    "garage_close",
    "garage_learn",
    "garage_open",
    "gate_close",
    "gate_learn",
    "gate_open",
    "light_learn",
    "light_off",
    "light_on",
    "mounted",
    "prepare_push_to_talk",
    "reboot",
    "halt",
    "rolling_shutter_down",
    "rolling_shutter_learn",
    "rolling_shutter_up",
    "measure_ambient_light",
    "stream_start",
    "stream_stop",
    "test_extend",
    "test_stop",
    "siren_3_sec",
    "test_start",
    "test_mfa",
    "sound_test",
]


class SomfyProtectApi:
    """Somfy Protect Api Class"""

    def __init__(self, sso: SomfyProtectSso):
        self.sso = sso

    def _request(self, method: str, path: str, base_url: str = BASE_URL, **kwargs: Any) -> Response:
        """Make a request.

        We don't use the built-in token refresh mechanism of OAuth2 session because
        we want to allow overriding the token refresh logic.

        Args:
            method (str): HTTP Methid
            path (str): Path to request

        Returns:
            Response: requests Response object
        """

        url = f"{base_url}{path}"
        try:
            return getattr(self.sso._oauth, method)(url, **kwargs)  # pylint: disable=protected-access
        except TokenExpiredError:
            self.sso._oauth.token = self.sso.refresh_tokens()  # pylint: disable=protected-access

            return getattr(self.sso._oauth, method)(url, **kwargs)  # pylint: disable=protected-access

    def get(self, path: str, base_url: str = BASE_URL) -> Response:
        """Fetch an URL from the Somfy Protect API.

        Args:
            path (str): Path to request

        Returns:
            Response: requests Response object
        """
        LOGGER.debug(f"{base_url}{path}")
        return self._request("get", path, base_url)

    def post(self, path: str, *, json: Dict[str, Any]) -> Response:
        """Post data to the Somfy Protect API.

        Args:
            path (str): Path to request
            json (Dict[str, Any]): Data in json format

        Returns:
            Response: requests Response object
        """
        return self._request("post", path, json=json)

    def put(self, path: str, *, json: Dict[str, Any]) -> Response:
        """Put data to the Somfy Protect API.

        Args:
            path (str): Path to request
            json (Dict[str, Any]): Data in json format

        Returns:
            Response: requests Response object
        """
        print(json)
        return self._request("put", path, json=json)

    def get_sites(self) -> List[Site]:
        """Get All Sites

        Returns:
            List[Site]: List of Site object
        """
        response = self.get("/v3/site")
        response.raise_for_status()
        return [Site(**s) for s in response.json().get("items")]

    def get_site(self, site_id: str) -> Site:
        """Get Site

        Args:
            site_id (str): Site ID


        Returns:
            Site: Site object
        """
        response = self.get(f"/v3/site/{site_id}")
        response.raise_for_status()
        return Site(**response.json())

    def get_site_scenario(self, site_id: str) -> Site:
        """Get Site

        Args:
            site_id (str): Site ID


        Returns:
            Site: Site object
        """
        response = self.get(f"/v4/api/site/{site_id}/device/all/scenario")
        response.raise_for_status()
        return response.json()

    def update_security_level(self, site_id: str, security_level: AvailableStatus) -> Dict:
        """Set Alarm Security Level

        Args:
            site_id (str): Site ID
            security_level (AvailableStatus): Security Level
        Returns:
            Dict: requests Response object
        """
        security_level = {"status": security_level.lower()}
        response = self.put(f"/v3/site/{site_id}/security", json=security_level)
        response.raise_for_status()
        return response.json()

    def stop_alarm(self, site_id: str) -> Dict:
        """Stop Current Alarm

        Args:
            site_id (str): Site ID
        Returns:
            Dict: requests Response object
        """
        response = self.put(f"/v3/site/{site_id}/alarm/stop", json={})
        response.raise_for_status()
        return response.json()

    def trigger_alarm(self, site_id: str, mode: str) -> Dict:
        """Trigger Alarm

        Args:
            site_id (str): Site ID
            mode (str): Mode (silent, alarm)
        Returns:
            Dict: requests Response object
        """
        if mode not in ["silent", "alarm"]:
            raise ValueError("Mode must be 'silent' or 'alarm'")
        payload = {"type": mode}
        response = self.post(f"/v3/site/{site_id}/panic", json=payload)
        response.raise_for_status()
        return response.json()

    def action_device(
        self,
        site_id: str,
        device_id: str,
        action: str,
        video_backend: Optional[str] = None,
    ) -> Dict:
        """Make an action on a Device

        Args:
            site_id (str): Site ID
            device_id (str): Device ID
            action (str): Action

        Returns:
            str: Task ID
        """
        if action not in ACTION_LIST:
            raise ValueError(f"Unknown action {action}")

        if video_backend:
            response = self.post(
                f"/v3/site/{site_id}/device/{device_id}/action",
                json={"action": action, "video_backend": video_backend},
            )
        else:
            response = self.post(
                f"/v3/site/{site_id}/device/{device_id}/action",
                json={"action": action},
            )
        response.raise_for_status()
        return response.json()

    def update_device(
        self,
        site_id: str,
        device_id: str,
        device_label: str,
        settings: Dict,
    ) -> Dict:
        """Update Device Settings

        Args:
            site_id (str): Site ID
            device_id (str): Device ID
            device_label (str): Device Label
            settings (Dict): Settings (as return by get_device)

        Returns:
            str: Task ID
        """
        if settings is None or device_label is None:
            raise ValueError("Missing settings and/or device_label")

        # Clean Settings Dict
        settings.pop("object")

        payload = {"settings": settings, "label": device_label}
        response = self.put(f"/v3/site/{site_id}/device/{device_id}", json=payload)
        response.raise_for_status()
        return response.json()

    def camera_snapshot(self, site_id: str, device_id: str) -> Device:
        """Get Camera Snapshot

        Args:
            site_id (str): Site ID
            device_id (str): Site ID

        Returns:
            Response: Response Image
        """
        response = self.post(
            f"/video/site/{site_id}/device/{device_id}/snapshot",
            json={"refresh": 10},
        )
        response.raise_for_status()
        if response.status_code == 200:
            return response

    def camera_refresh_snapshot(self, site_id: str, device_id: str) -> Device:
        """Get Camera Snapshot

        Args:
            site_id (str): Site ID
            device_id (str): Site ID

        Returns:
            Task: Somfy Task
        """
        response = self.post(
            f"/video/site/{site_id}/device/{device_id}/refresh-snapshot",
            json={},
        )
        response.raise_for_status()
        return response.json()

    def get_devices(self, site_id: str, category: Optional[Category] = None) -> List[Device]:
        """List Devices from a Site ID

        Args:
            site_id (Optional[str], optional): Site ID. Defaults to None.
            category (Optional[Category], optional): [description]. Defaults to None.

        Returns:
            List[Device]: List of Device object
        """
        devices = []  # type: List[Device]
        response = self.get(f"/v3/site/{site_id}/device")
        try:
            content = response.json()
        except JSONDecodeError:
            response.raise_for_status()
        LOGGER.debug(f"Devices Capabilities: {response.json()}")
        devices += [
            Device(**d)
            for d in content.get("items")
            if category is None or category.value.lower() in Device(**d).device_definition.get("label").lower()
        ]

        return devices

    def get_device(self, site_id: str, device_id: str) -> Device:
        """Get Device details

        Args:
            site_id (str): Site ID
            device_id (str): Site ID

        Returns:
            Device: Device object
        """
        response = self.get(f"/v3/site/{site_id}/device/{device_id}")
        response.raise_for_status()
        return Device(**response.json())

    def get_users(self, site_id: str) -> List[User]:
        """List Users from a Site ID

        Args:
            site_id[str]: Site ID. Defaults to None.

        Returns:
            List[User]: List of User object
        """
        response = self.get(f"/v3/site/{site_id}/user")
        print(response)
        response.raise_for_status()
        return [User(**s) for s in response.json().get("items")]

    def get_user(self, site_id: str, user_id: str) -> User:
        """Get User details

        Args:
            site_id (str): Site ID
            user_id (str): Site ID

        Returns:
            User: User object
        """
        response = self.get(f"/v3/site/{site_id}/user/{user_id}")
        print(response)
        response.raise_for_status()
        return response.json()

    def action_user(
        self,
        site_id: str,
        user_id: str,
        action: str,
    ) -> Dict:
        """Make an action on a User

        Args:
            site_id (str): Site ID
            user_id (str): User ID
            action (str): Action

        Returns:
            str: Task ID
        """
        if action not in ACTION_LIST:
            raise ValueError(f"Unknown action {action}")

        response = self.post(
            f"/v3/site/{site_id}/user/{user_id}/action",
            json={"action": action},
        )
        response.raise_for_status()
        return response.json()

    def get_scenarios_core(
        self,
        site_id: str,
    ):
        """Get Scenarios Core

        Args:
            site_id (str): Site ID

        Returns:
            ??
        """
        response = self.get(f"/v3/site/{site_id}/scenario-core")
        response.raise_for_status()
        return response.json()

    def get_scenarios(
        self,
        site_id: str,
    ):
        """Get Scenarios

        Args:
            site_id (str): Site ID

        Returns:
            ??
        """
        response = self.get(f"/v3/site/{site_id}/scenario")
        response.raise_for_status()
        return response.json()

    def test_siren(self, site_id: str, device_id: str, sound: str) -> Dict:
        """Test Siren

        Args:
            site_id (str): Site ID
            device_id (str) Device ID
            sound (str): Sound (smokeExtended, siren1s, armed, disarmed, intrusion, ok)
        Returns:
            Dict: requests Response object
        """
        if sound not in [
            "smokeExtended",
            "siren1s",
            "armed",
            "disarmed",
            "intrusion",
            "ok",
        ]:
            raise ValueError("Sound value is not valid")
        response = self.post(f"/v3/site/{site_id}/device/{device_id}/sound/{sound}", json={})
        response.raise_for_status()
        return response.json()

    def get_history(
        self,
        site_id: str,
    ):
        """Get Scenarios

        Args:
            site_id (str): Site ID

        Returns:
            ??
        """
        # response = self.get(f"/v3/site/{site_id}/history?order=-1&limit=100")
        response = self.get(f"/v3/site/{site_id}/history")
        response.raise_for_status()
        return response.json().get("items")

    def get_device_events(
        self,
        site_id: str,
        device_id: str,
    ):
        """Get Device Events

        Args:
            site_id (str): Site ID
            device_id (str): Device ID

        Returns:
            ??
        """
        token = read_token_from_file().get("access_token")
        response = self.get(f"/event/site/{site_id}/device/{device_id}/events?access_token={token}", base_url=VIDEO_URL)
        LOGGER.info(response.json())
        response.raise_for_status()
        return response.json()

    def trigger_access(
        self,
        site_id: str,
        device_id: str,
        access: str,
    ) -> Dict:
        """Make an action on a Device

        Args:
            site_id (str): Site ID
            device_id (str): Device ID
            access (str): Access

        Returns:
            str: Task ID
        """
        if access not in ACCESS_LIST:
            raise ValueError(f"Unknown action {access}")

        response = self.post(
            f"/v3/site/{site_id}/device/{device_id}/access/trigger",
            json={"type": access},
        )
        response.raise_for_status()
        return response.json()

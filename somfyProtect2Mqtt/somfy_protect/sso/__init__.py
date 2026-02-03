"""Somfy Protect Sso"""

import base64
import json
import logging
import os
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional, Union

from exceptions import SomfyProtectInitError
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError
from requests import Response
from requests_oauthlib import OAuth2Session

LOGGER = logging.getLogger(__name__)

SOMFY_PROTECT_TOKEN = "https://sso.myfox.io/oauth/oauth/v2/token/jwt"

CLIENT_ID = "ODRlZGRmNDgtMmI4ZS0xMWU1LWIyYTUtMTI0Y2ZhYjI1NTk1XzQ3NWJ1cXJmOHY4a2d3b280Z293MDhna2tjMGNrODA0ODh3bzQ0czhvNDhzZzg0azQw"  # pylint: disable=line-too-long
CLIENT_SECRET = "NGRzcWZudGlldTB3Y2t3d280MGt3ODQ4Z3c0bzBjOGs0b3djODBrNGdvMGNzMGs4NDQ="

CACHE_PATH = "token.json"


def read_token_from_file(cache_path: dict = CACHE_PATH) -> Dict:
    """Retrieve a token from a file"""
    try:
        with open(file=cache_path, mode="r", encoding="utf8") as cache:
            return json.loads(cache.read())
    except IOError:
        return {}


def write_token_to_file(token, cache_path: dict = CACHE_PATH) -> None:
    """Write a token into a file"""
    with open(file=cache_path, mode="w", encoding="utf8") as cache:
        cache.write(json.dumps(token))


class SomfyProtectSso:
    """Somfy Protect Sso"""

    def __init__(
        self,
        username: str,
        password: str,
        token: Optional[Dict[str, str]] = None,
        token_updater: Optional[Callable[[str], None]] = write_token_to_file,
    ):
        self.username = username
        self.password = password
        self.client_id = base64.b64decode(CLIENT_ID).decode("utf-8")
        self.client_secret = base64.b64decode(CLIENT_SECRET).decode("utf-8")
        self.token_updater = token_updater

        # Load token from file if not provided
        if token is None:
            token = read_token_from_file()

        extra = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        self._oauth = OAuth2Session(
            client=LegacyApplicationClient(client_id=self.client_id),
            token=token,
            auto_refresh_kwargs=extra,
            token_updater=token_updater,
        )
        self._oauth.headers["User-Agent"] = "Somfy Protect"

    def request_token(
        self,
    ) -> Dict[str, str]:
        """Generic method for fetching a Somfy Protect access token.

        Returns:
            Dict[str, str]: Token
        """
        LOGGER.info("Requesting Token")
        return self._oauth.fetch_token(
            SOMFY_PROTECT_TOKEN,
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            client_secret=self.client_secret,
            include_client_id=True,
        )

    def refresh_tokens(self) -> Dict[str, Union[str, int]]:
        """Refresh and return new Somfy tokens.

        Returns:
            Dict[str, Union[str, int]]: Token
        """
        LOGGER.info("Refreshing Token")
        token = self._oauth.refresh_token(SOMFY_PROTECT_TOKEN)

        if self.token_updater is not None:
            self.token_updater(token)

        LOGGER.info(f"New Token: {token}")
        return token


def init_sso(config: dict) -> None:
    """Init SSO

    Args:
        config (dict): Global Configuration

    Raises:
        SomfyProtectInitError: Unable to init
    """
    logging.info("Init SSO")
    username = config.get("somfy_protect").get("username")
    password = config.get("somfy_protect").get("password")
    if username is None or password is None:
        raise SomfyProtectInitError("Username/Password is missing in config")

    sso = SomfyProtectSso(username=username, password=password)
    if not os.path.isfile(CACHE_PATH):
        token = sso.request_token()
        write_token_to_file(token)
    return sso

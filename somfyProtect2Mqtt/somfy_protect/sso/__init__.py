"""Somfy Protect Sso"""

import base64
import json
import logging
import os
import tempfile
import threading
from json import JSONDecodeError
from typing import Any, Callable, Dict, Optional

from exceptions import SomfyProtectInitError
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError
from requests import RequestException
from requests import Response
from requests_oauthlib import OAuth2Session
from utils import build_retry_adapter

LOGGER = logging.getLogger(__name__)

SOMFY_PROTECT_TOKEN = "https://sso.myfox.io/oauth/oauth/v2/token/jwt"

CLIENT_ID = (
    "ODRlZGRmNDgtMmI4ZS0xMWU1LWIyYTUtMTI0Y2ZhYjI1NTk1XzQ3NWJ1cXJmOHY4a2d3"
    "b280Z293MDhna2tjMGNrODA0ODh3bzQ0czhvNDhzZzg0azQw"
)
CLIENT_SECRET = "NGRzcWZudGlldTB3Y2t3d280MGt3ODQ4Z3c0bzBjOGs0b3djODBrNGdvMGNzMGs4NDQ="

DEFAULT_CACHE_FILENAME = "token.json"


def resolve_token_cache_path(config_file: str | None = None) -> str:
    """Resolve the token cache path.

    Args:
        config_file (str | None): Config file path.

    Returns:
        str: Token cache path.
    """
    if config_file:
        config_dir = os.path.dirname(os.path.abspath(config_file))
        if config_dir:
            return os.path.join(config_dir, DEFAULT_CACHE_FILENAME)
    return DEFAULT_CACHE_FILENAME


def read_token_from_file(cache_path: str = DEFAULT_CACHE_FILENAME) -> Dict[str, Any]:
    """Retrieve a token from a file."""
    try:
        with open(file=cache_path, mode="r", encoding="utf8") as cache:
            return json.loads(cache.read())
    except (IOError, JSONDecodeError):
        return {}


def write_token_to_file(token: Dict[str, Any], cache_path: str = DEFAULT_CACHE_FILENAME) -> None:
    """Write a token into a file."""
    cache_dir = os.path.dirname(os.path.abspath(cache_path))
    if cache_dir:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".token-", dir=cache_dir or None, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, mode="w", encoding="utf8") as cache:
            cache.write(json.dumps(token))
        os.replace(tmp_path, cache_path)
        os.chmod(cache_path, 0o600)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def build_token_updater(cache_path: str) -> Callable[[Dict[str, Any]], None]:
    """Create a token updater bound to a cache path.

    Args:
        cache_path (str): Token cache path.

    Returns:
        Callable[[Dict[str, Any]], None]: Token updater callback.
    """

    def _token_updater(token: Dict[str, Any]) -> None:
        write_token_to_file(token, cache_path)

    return _token_updater


class SomfyProtectSso:
    """Somfy Protect Sso"""

    def __init__(
        self,
        username: str,
        password: str,
        token: Optional[Dict[str, Any]] = None,
        token_cache_path: str = DEFAULT_CACHE_FILENAME,
        token_updater: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.username = username
        self.password = password
        self.token_cache_path = token_cache_path
        self._oauth_lock = threading.RLock()
        self.client_id = base64.b64decode(CLIENT_ID).decode("utf-8")
        self.client_secret = base64.b64decode(CLIENT_SECRET).decode("utf-8")
        if token_updater is None:
            token_updater = build_token_updater(self.token_cache_path)
        self.token_updater = token_updater

        extra = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        if token is None:
            token = read_token_from_file(self.token_cache_path)
        self._oauth = OAuth2Session(
            client=LegacyApplicationClient(client_id=self.client_id),
            token=token,
            auto_refresh_kwargs=extra,
            token_updater=token_updater,
        )
        self._oauth.headers["User-Agent"] = "Somfy Protect"
        adapter = build_retry_adapter([429, 500, 502, 503, 504])
        self._oauth.mount("https://", adapter)
        self._oauth.mount("http://", adapter)

    @property
    def oauth(self) -> OAuth2Session:
        """Expose the underlying OAuth2 session."""
        return self._oauth

    def get_token(self) -> Dict[str, Any]:
        """Return a shallow copy of the current token."""
        with self._oauth_lock:
            token = self._oauth.token or {}
            return dict(token)

    def set_token(self, token: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a new token in the shared OAuth session."""
        with self._oauth_lock:
            self._oauth.token = token
        return token

    def request(
        self,
        method: str,
        url: str,
        retry_on_auth_error: bool = True,
        **kwargs: Any,
    ) -> tuple[Response, bool]:
        """Run a synchronized OAuth request.

        Args:
            method (str): HTTP method name.
            url (str): Fully qualified URL.
            retry_on_auth_error (bool): Retry once after token refresh on 401/403.
            **kwargs: Extra request arguments.

        Returns:
            tuple[Response, bool]: Response and whether a refresh happened.
        """
        refreshed = False
        with self._oauth_lock:
            response, expired_refresh = self._request_locked(method, url, **kwargs)
            refreshed = refreshed or expired_refresh
            if retry_on_auth_error and response.status_code in (401, 403):
                self._refresh_tokens_locked()
                refreshed = True
                response, expired_refresh = self._request_locked(method, url, **kwargs)
                refreshed = refreshed or expired_refresh
        return response, refreshed

    def _request_locked(self, method: str, url: str, **kwargs: Any) -> tuple[Response, bool]:
        try:
            return getattr(self._oauth, method)(url, **kwargs), False
        except TokenExpiredError:
            self._refresh_tokens_locked()
            return getattr(self._oauth, method)(url, **kwargs), True

    def _request_token_locked(self) -> Dict[str, Any]:
        LOGGER.info("Requesting Token")
        token = self._oauth.fetch_token(
            SOMFY_PROTECT_TOKEN,
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            client_secret=self.client_secret,
            include_client_id=True,
        )
        self._oauth.token = token
        return token

    def _refresh_tokens_locked(self) -> Dict[str, Any]:
        LOGGER.info("Refreshing Token")
        try:
            token = self._oauth.refresh_token(SOMFY_PROTECT_TOKEN)
        except (RequestException, TokenExpiredError, ValueError) as e:
            LOGGER.warning("Refresh failed, requesting new token: {}".format(e))
            token = self._request_token_locked()
        else:
            self._oauth.token = token

        if self.token_updater is not None:
            self.token_updater(token)

        LOGGER.info("New Token: ****")
        return token

    def request_token(
        self,
    ) -> Dict[str, Any]:
        """Generic method for fetching a Somfy Protect access token.

        Returns:
            Dict[str, Any]: Token
        """
        with self._oauth_lock:
            return self._request_token_locked()

    def refresh_tokens(self) -> Dict[str, Any]:
        """Refresh and return new Somfy tokens.

        Returns:
            Dict[str, Any]: Token
        """
        with self._oauth_lock:
            return self._refresh_tokens_locked()


def init_sso(config: dict, config_file: str | None = None) -> Optional[SomfyProtectSso]:
    """Init SSO

    Args:
        config (dict): Global Configuration

    Raises:
        SomfyProtectInitError: Unable to init
    """
    logging.info("Init SSO")
    somfy_config = config.get("somfy_protect") or {}
    username = somfy_config.get("username")
    password = somfy_config.get("password")
    if username is None or password is None:
        raise SomfyProtectInitError("Username/Password is missing in config")

    cache_path = resolve_token_cache_path(config_file)
    sso = SomfyProtectSso(username=username, password=password, token_cache_path=cache_path)
    if not os.path.isfile(cache_path):
        token = sso.request_token()
        write_token_to_file(token, cache_path)
    return sso

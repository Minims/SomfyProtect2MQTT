"""Somfy Protect Api related calls"""

import json
import logging
import os

from somfy_protect_api.api.somfy_protect_api import SomfyProtectApi

CACHE_PATH = "token.json"
LOGGER = logging.getLogger(__name__)


def get_token(cache_path: dict = CACHE_PATH):
    """Retrieve a token from a file
    """
    try:
        with open(cache_path, "r") as cache:
            return json.loads(cache.read())
    except IOError:
        pass


def set_token(token, cache_path: dict = CACHE_PATH) -> None:
    """Write a token into a file
    """
    with open(cache_path, "w") as cache:
        cache.write(json.dumps(token))


def init_somfy_protect(
    username: str, password: str, cache_path: dict = CACHE_PATH
):
    """Init Somfy Api
    """
    api = SomfyProtectApi(
        username=username,
        password=password,
        token=get_token(),
        token_updater=set_token,
    )

    # Check if we already have a token
    if not os.path.isfile(cache_path):
        set_token(api.request_token())

    return api

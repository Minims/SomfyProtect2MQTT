"""Utils package"""
import codecs
import logging
import logging.handlers
import os
from typing import Any, Dict
import sys

import yaml
from yaml.parser import ParserError

LOGGER = logging.getLogger(__name__)


def setup_logger(debug: bool = False, filename: str = "/var/log/somfyProtect.log") -> None:
    """Setup Logging
    Args:
        debug (bool, optional): True if debug enabled. Defaults to False.
        filename (str, optional): log filename. Defaults to "/var/log/somfyProtect.log".
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(filename=filename),],
    )


def read_config_file(config_file: str) -> Dict[str, Any]:
    """Read config file

    Args:
        config_file (str): config_file

    Returns:
        Dict[str, Any]: Config in json
    """
    logging.info(f"Reading config file {config_file}")
    if not os.path.isfile(config_file):
        LOGGER.error(f"File {config_file} not found")
        return {}

    with codecs.open(config_file, "r", "utf8") as file_handler:
        try:
            conf = yaml.load(file_handler, Loader=yaml.FullLoader)
        except ParserError:
            logging.warning(f"Unable to parse config file {config_file}")
            conf = None
    if conf is None:
        conf = {}
    return conf


def close_and_exit(robot, code: int = 0, signal: int = None, frame=None,) -> None:  # pylint: disable=unused-argument
    """Close & Exit

    Args:
        robot ([type]): SomfyProtect2Mqtt
        code (int, optional): Code to return. Defaults to 0.
        signal (int, optional): Signal Received. Defaults to None.
        frame ([type], optional): Not Used. Defaults to None.
    """
    if signal:
        LOGGER.debug(f"Signal {signal} received")
    LOGGER.info("Stopping Application")
    if robot:
        robot.close()
    sys.exit(code)

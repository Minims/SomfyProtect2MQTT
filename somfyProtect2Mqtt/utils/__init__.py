"""Utils package"""

import codecs
import logging
import logging.handlers
import os
import sys
from typing import Any, Dict

import yaml
from yaml.parser import ParserError

LOGGER = logging.getLogger(__name__)


def setup_logger(debug: bool = False, filename: str = "/var/log/somfyProtect.log") -> None:
    """Configure logging.

    Args:
        debug (bool): Enable debug logging when True.
        filename (str): Log filename.
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(filename=filename),
        ],
    )


def read_config_file(config_file: str) -> Dict[str, Any]:
    """Read a YAML config file.

    Args:
        config_file (str): Config file path.

    Returns:
        Dict[str, Any]: Parsed config dictionary.
    """
    if not config_file:
        LOGGER.error("Config file path is missing")
        return {}
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


def close_and_exit(
    robot,
    code: int = 0,
    signal: int = None,
    _frame=None,
) -> None:
    """Close resources and exit.

    Args:
        robot: SomfyProtect2Mqtt instance.
        code (int): Exit code.
        signal (int): Signal received.
        frame: Signal frame (unused).
    """
    if signal:
        LOGGER.debug(f"Signal {signal} received")
    LOGGER.info("Stopping Application")
    if robot:
        robot.close()
    sys.exit(code)

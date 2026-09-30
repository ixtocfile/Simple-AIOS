"""File logging owned by Simple-AIOS; leave the root logger untouched."""

import logging

from aios.config import Config


def configure_logging(config: Config) -> logging.Logger:
    level = logging.getLevelName(config.log_level)
    if not isinstance(level, int):
        raise ValueError("Invalid log_level")

    directory = config.data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(directory / "simple-aios.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    logger = logging.getLogger("aios")
    close_logging()
    # NOTSET should include all standard levels, not inherit the root threshold.
    logger.setLevel(level or logging.DEBUG)
    logger.propagate = False
    logger.disabled = False
    logger.addHandler(handler)
    return logger


def close_logging() -> None:
    logger = logging.getLogger("aios")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

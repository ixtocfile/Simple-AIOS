"""Verify real log files, filtering and handler lifecycle."""

import logging
import re

import pytest

from aios.app_logging import close_logging, configure_logging
from aios.config import Config


@pytest.fixture(autouse=True)
def cleanup_logging():
    yield
    close_logging()


@pytest.mark.parametrize(
    ("level", "debug_visible", "info_visible"),
    [("DEBUG", True, True), ("INFO", False, True),
     ("ERROR", False, False), ("NOTSET", True, True)],
)
def test_level_and_timestamp_in_utf8_file(tmp_path, level, debug_visible, info_visible):
    logger = configure_logging(Config(data_dir=tmp_path, log_level=level))
    logger.debug("debug event")
    logger.info("info event")
    logger.error("Échec de test")
    close_logging()

    logs = (tmp_path / "logs/simple-aios.log").read_text(encoding="utf-8")
    assert ("debug event" in logs) == debug_visible
    assert ("info event" in logs) == info_visible
    assert "ERROR Échec de test" in logs
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", logs)


def test_reconfiguration_appends_without_duplicates_or_root_changes(tmp_path, caplog):
    root = logging.getLogger()
    root_state = (root.level, root.handlers[:])
    config = Config(data_dir=tmp_path)
    logger = configure_logging(config)
    logger.info("first event")
    old_handler = logger.handlers[0]

    logger = configure_logging(config)
    logger.info("second event")
    new_handler = logger.handlers[0]
    close_logging()

    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert logs.count("first event") == 1
    assert logs.count("second event") == 1
    assert old_handler.stream is None
    assert new_handler.stream is None
    assert not logger.handlers
    assert (root.level, root.handlers) == root_state
    assert not caplog.records

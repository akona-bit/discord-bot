"""Tests for the logging setup in tle.__main__.

UTF-8 forcing on the console streams and the rotating file handler.
"""

import io
import logging
from logging.handlers import TimedRotatingFileHandler

import pytest

from tle import constants
from tle.__main__ import force_utf8_console, setup

# Contains 'Đ' and 'ỏ', neither of which cp1252 can encode.
VIETNAMESE_MESSAGE = 'Đã bỏ qua thử thách.'


@pytest.fixture
def run_setup(monkeypatch, tmp_path):
    """Return a callable running setup() on a clean root logger, logging to a
    temporary file whose path it returns."""
    log_file = tmp_path / 'logs' / 'tle.log'
    monkeypatch.setattr(constants, 'ALL_DIRS', (log_file.parent,))
    monkeypatch.setattr(constants, 'LOG_FILE_PATH', log_file)

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    def _run():
        # basicConfig is a no-op unless the root logger starts out without
        # handlers, and pytest installs its own capture handlers there.
        root.handlers = []
        setup()
        return log_file

    yield _run
    for handler in root.handlers:
        handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)


class TestForceUtf8Console:
    def test_streams_are_reconfigured_to_utf8(self, monkeypatch):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        stderr = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        monkeypatch.setattr('sys.stdout', stdout)
        monkeypatch.setattr('sys.stderr', stderr)

        force_utf8_console()

        assert stdout.encoding.lower() == 'utf-8'
        assert stderr.encoding.lower() == 'utf-8'

    def test_vietnamese_text_survives_a_cp1252_stream(self, monkeypatch):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding='cp1252')
        monkeypatch.setattr('sys.stdout', stream)
        monkeypatch.setattr('sys.stderr', stream)
        with pytest.raises(UnicodeEncodeError):
            stream.write(VIETNAMESE_MESSAGE)

        force_utf8_console()
        stream.write(VIETNAMESE_MESSAGE)
        stream.flush()

        assert buffer.getvalue().decode('utf-8') == VIETNAMESE_MESSAGE

    def test_stream_without_reconfigure_is_skipped(self, monkeypatch):
        monkeypatch.setattr('sys.stdout', io.StringIO())
        monkeypatch.setattr('sys.stderr', io.StringIO())

        force_utf8_console()

    def test_unreconfigurable_stream_is_tolerated(self, monkeypatch):
        class DetachedStream:
            def reconfigure(self, **kwargs):
                raise ValueError('underlying buffer has been detached')

        monkeypatch.setattr('sys.stdout', DetachedStream())
        monkeypatch.setattr('sys.stderr', DetachedStream())

        force_utf8_console()


class TestSetup:
    def test_file_handler_gets_an_explicit_utf8_encoding(self, monkeypatch, run_setup):
        # The encoding has to be passed explicitly: without it the handler opens
        # the log file with the host locale encoding, cp1252 on Windows.
        recorded = {}

        class RecordingHandler(TimedRotatingFileHandler):
            def __init__(self, filename, **kwargs):
                recorded.update(kwargs)
                super().__init__(filename, **kwargs)

        monkeypatch.setattr('tle.__main__.TimedRotatingFileHandler', RecordingHandler)

        run_setup()

        assert recorded['encoding'] == 'utf-8'

    def test_vietnamese_log_line_is_written_to_file(self, run_setup):
        log_file = run_setup()

        logging.getLogger('test').info(VIETNAMESE_MESSAGE)
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert VIETNAMESE_MESSAGE in log_file.read_text(encoding='utf-8')

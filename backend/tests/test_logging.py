"""Tests for the structured JSON logging system."""

import json
import logging

import pytest
from core.logging_config import (
    ContextFilter,
    JSONFormatter,
    clear_request_context,
    set_request_context,
)


class TestJSONFormatter:
    """Test JSON log output format."""

    def setup_method(self):
        self.formatter = JSONFormatter()
        self.logger = logging.getLogger("test.json")
        self.logger.handlers = []
        self.handler = logging.StreamHandler()
        self.handler.setFormatter(self.formatter)
        self.logger.addHandler(self.handler)

    def test_basic_format(self):
        record = logging.LogRecord(
            name="test.json",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = self.formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test.json"
        assert data["msg"] == "Hello world"
        assert "ts" in data

    def test_timestamp_is_iso(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        output = self.formatter.format(record)
        data = json.loads(output)
        # ISO format: 2026-02-11T09:30:00.123456+00:00
        assert "T" in data["ts"]
        assert "+" in data["ts"] or "Z" in data["ts"]

    def test_exception_included(self):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error occurred", args=(), exc_info=sys.exc_info(),
            )
        output = self.formatter.format(record)
        data = json.loads(output)
        assert "exc" in data
        assert data["exc"] is not None

    def test_single_line_json(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="multi\nline\nmessage", args=(), exc_info=None,
        )
        output = self.formatter.format(record)
        # JSON output should be a single line (no embedded newlines in JSON wrapper)
        assert output.count("\n") == 0
        data = json.loads(output)
        assert "multi\nline\nmessage" in data["msg"]


class TestContextFilter:
    """Test request context injection into log records."""

    def setup_method(self):
        clear_request_context()

    def teardown_method(self):
        clear_request_context()

    def test_default_empty_context(self):
        filt = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        filt.filter(record)
        assert record.request_id == ""
        assert record.request_method == ""
        assert record.request_path == ""

    def test_context_injected(self):
        set_request_context(request_id="abc123", method="GET", path="/api/status")
        filt = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        filt.filter(record)
        assert record.request_id == "abc123"
        assert record.request_method == "GET"
        assert record.request_path == "/api/status"

    def test_context_cleared(self):
        set_request_context(request_id="abc123", method="GET", path="/api/test")
        clear_request_context()
        filt = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        filt.filter(record)
        assert record.request_id == ""

    def test_filter_always_returns_true(self):
        filt = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        assert filt.filter(record) is True


class TestJSONFormatterWithContext:
    """Test JSON output includes request context."""

    def setup_method(self):
        clear_request_context()

    def teardown_method(self):
        clear_request_context()

    def test_request_id_in_json(self):
        set_request_context(request_id="req-42", method="POST", path="/api/chat")
        formatter = JSONFormatter()
        filt = ContextFilter()

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Processing request", args=(), exc_info=None,
        )
        filt.filter(record)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-42"
        assert data["method"] == "POST"
        assert data["path"] == "/api/chat"

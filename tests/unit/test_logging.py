import json
import logging

from reaper_mcp.logging import JsonLogFormatter


def test_json_log_formatter_emits_structured_bridge_fields() -> None:
    record = logging.LogRecord(
        name="reaper_mcp.bridge",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="bridge_command_completed",
        args=(),
        exc_info=None,
    )
    record.event = "bridge_command_completed"
    record.request_id = "request-1"
    record.command = "health_check"
    record.duration_ms = 12.5
    record.result = "ok"
    record.target_ids = {}

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "info"
    assert payload["event"] == "bridge_command_completed"
    assert payload["request_id"] == "request-1"
    assert payload["command"] == "health_check"
    assert payload["duration_ms"] == 12.5
    assert payload["result"] == "ok"
    assert payload["target_ids"] == {}

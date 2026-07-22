import pytest
from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import (
    BridgeResponse,
    CommandEnvelope,
    CommandOptions,
    ErrorResponse,
)


def test_command_envelope_defaults_to_read_only_options() -> None:
    envelope = CommandEnvelope(command="health_check")

    assert envelope.command == "health_check"
    assert envelope.args == {}
    assert envelope.options.mutates_project is False
    assert envelope.options.dry_run is False


def test_mutating_command_options_require_undo_label() -> None:
    with pytest.raises(ValidationError):
        CommandOptions(mutates_project=True)


def test_mutating_dry_run_can_omit_undo_label() -> None:
    options = CommandOptions(mutates_project=True, dry_run=True)

    assert options.undo_label is None


def test_failed_bridge_response_requires_error() -> None:
    with pytest.raises(ValidationError):
        BridgeResponse(id="request-1", ok=False)


def test_error_response_accepts_stable_error_code() -> None:
    response = BridgeResponse(
        id="request-1",
        ok=False,
        error=ErrorResponse(
            code=ErrorCode.BRIDGE_NOT_RUNNING,
            message="The REAPER Lua bridge is not running.",
        ),
    )

    assert response.error is not None
    assert response.error.code == ErrorCode.BRIDGE_NOT_RUNNING

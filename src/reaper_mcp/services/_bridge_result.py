"""Shared structured error helpers for bridge-backed services."""

import json
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, ErrorResponse


def bridge_error(response: BridgeResponse) -> dict[str, Any]:
    """Return one bridge error without changing its stable code."""

    return {
        "ok": False,
        "error": response.error.model_dump(mode="json") if response.error else None,
        "warnings": response.warnings,
    }


def invalid_payload(
    response: BridgeResponse,
    exc: ValidationError,
    payload_name: str,
) -> dict[str, Any]:
    """Return a stable error for a malformed bridge result."""

    return {
        "ok": False,
        "error": ErrorResponse(
            code=ErrorCode.INVALID_BRIDGE_RESPONSE,
            message=f"The Lua bridge returned an invalid {payload_name} payload.",
            details={"errors": _validation_errors(exc)},
            recoverable=True,
            suggested_action="Restart the Lua bridge and retry the command.",
        ).model_dump(mode="json"),
        "warnings": response.warnings,
    }


def validation_error(
    exc: ValidationError,
    code: ErrorCode,
    message: str,
    suggested_action: str,
) -> dict[str, Any]:
    """Return a stable pre-bridge validation error."""

    return {
        "ok": False,
        "error": ErrorResponse(
            code=code,
            message=message,
            details={"errors": _validation_errors(exc)},
            recoverable=True,
            suggested_action=suggested_action,
        ).model_dump(mode="json"),
        "warnings": [],
    }


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Return Pydantic errors with JSON-safe context values."""

    return json.loads(exc.json(include_url=False))

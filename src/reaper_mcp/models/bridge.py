"""Shared bridge protocol models."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.errors import ErrorCode


class CommandOptions(BaseModel):
    """Execution options for one bridge command."""

    mutates_project: bool = False
    undo_label: str | None = None
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_undo_label_for_mutations(self) -> "CommandOptions":
        """Require future mutating commands to be undoable by default."""

        if self.mutates_project and not self.dry_run and not self.undo_label:
            msg = "Mutating commands require an undo label."
            raise ValueError(msg)
        return self


class CommandEnvelope(BaseModel):
    """A command sent from Python to the REAPER Lua bridge."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    command: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    options: CommandOptions = Field(default_factory=CommandOptions)


class ErrorResponse(BaseModel):
    """Structured error returned to MCP clients and bridge callers."""

    code: ErrorCode | str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    recoverable: bool = True
    suggested_action: str | None = None


class BridgeResponse(BaseModel):
    """A response from the REAPER Lua bridge."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: ErrorResponse | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_response_shape(self) -> "BridgeResponse":
        """Keep success and error responses unambiguous."""

        if self.ok and self.error is not None:
            msg = "Successful bridge responses cannot include an error."
            raise ValueError(msg)
        if not self.ok and self.error is None:
            msg = "Failed bridge responses must include an error."
            raise ValueError(msg)
        return self

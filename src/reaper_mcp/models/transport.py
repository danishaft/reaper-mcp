"""Typed transport models."""

from pydantic import BaseModel, ConfigDict


class TransportState(BaseModel):
    """Current REAPER transport state."""

    model_config = ConfigDict(extra="forbid")

    play_state: int = 0
    playing: bool = False
    paused: bool = False
    recording: bool = False


class TransportActionResult(BaseModel):
    """Result returned after a transport command."""

    model_config = ConfigDict(extra="forbid")

    action: str
    transport: TransportState
    may_create_media_items: bool = False

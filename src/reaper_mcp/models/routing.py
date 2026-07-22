"""Typed track routing models."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrackSendSnapshot(BaseModel):
    """Read-only state for one track send."""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1)
    source_track_guid: str = Field(min_length=1)
    destination_track_guid: str = Field(min_length=1)
    destination_track_name: str = ""
    index: int = Field(ge=0)
    volume: float = Field(ge=0.0)
    pan: float = Field(ge=-1.0, le=1.0)
    muted: bool = False


class TrackSendList(BaseModel):
    """Read-only sends for one source track."""

    model_config = ConfigDict(extra="forbid")

    source_track_guid: str = Field(min_length=1)
    sends: list[TrackSendSnapshot] = Field(default_factory=list)
    send_count: int = Field(ge=0)


class TrackSendIdentity(BaseModel):
    """Guarded send identity using source, slot, and destination."""

    model_config = ConfigDict(extra="forbid")

    source_track_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    expected_destination_track_guid: str = Field(min_length=1)


class CreateTrackSendRequest(BaseModel):
    """Input for creating one track send."""

    model_config = ConfigDict(extra="forbid")

    source_track_guid: str = Field(min_length=1)
    destination_track_guid: str = Field(min_length=1)
    volume: float = Field(default=1.0, ge=0.0, le=4.0)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)
    muted: bool = False

    @model_validator(mode="after")
    def reject_self_send(self) -> Self:
        """Reject a source routed directly back to itself."""

        if self.source_track_guid == self.destination_track_guid:
            raise ValueError("source and destination tracks must differ")
        return self


class CreateTrackSendResult(BaseModel):
    """Result returned after creating one track send."""

    model_config = ConfigDict(extra="forbid")

    send: TrackSendSnapshot
    send_count: int = Field(ge=1)
    changes_applied: bool = True


class SetTrackSendRequest(BaseModel):
    """Input for changing guarded track send properties."""

    model_config = ConfigDict(extra="forbid")

    send_identity: TrackSendIdentity
    volume: float | None = Field(default=None, ge=0.0, le=4.0)
    pan: float | None = Field(default=None, ge=-1.0, le=1.0)
    muted: bool | None = None

    @model_validator(mode="after")
    def require_one_change(self) -> Self:
        """Require at least one send property update."""

        if self.volume is None and self.pan is None and self.muted is None:
            raise ValueError("at least one send property must be provided")
        return self


class SetTrackSendResult(BaseModel):
    """Result returned after changing one track send."""

    model_config = ConfigDict(extra="forbid")

    send: TrackSendSnapshot
    changes_applied: bool = True


class RemoveTrackSendRequest(BaseModel):
    """Input for removing one guarded track send."""

    model_config = ConfigDict(extra="forbid")

    send_identity: TrackSendIdentity


class RemoveTrackSendResult(BaseModel):
    """Result returned after removing one track send."""

    model_config = ConfigDict(extra="forbid")

    source_track_guid: str = Field(min_length=1)
    destination_track_guid: str = Field(min_length=1)
    removed_index: int = Field(ge=0)
    send_count: int = Field(ge=0)
    changes_applied: bool = True

"""Typed REAPER fixed-lane state and guarded selection requests."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FixedLaneItemSnapshot(BaseModel):
    """One media item assigned to a fixed lane."""

    model_config = ConfigDict(extra="forbid")

    guid: str = Field(min_length=1)
    position_seconds: float = Field(ge=0.0)
    length_seconds: float = Field(ge=0.0)
    muted: bool


class FixedLaneSnapshot(BaseModel):
    """One lane in the current REAPER fixed-lane layout."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str = ""
    play_state: Literal[0, 1, 2]
    items: list[FixedLaneItemSnapshot] = Field(default_factory=list)


class FixedLaneLayout(BaseModel):
    """Current fixed-lane state bound to one track and layout fingerprint."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    lane_count: int = Field(ge=1)
    layout_fingerprint: str = Field(min_length=1)
    lanes: list[FixedLaneSnapshot]
    changes_applied: bool = False

    @model_validator(mode="after")
    def validate_lane_layout(self) -> Self:
        if self.lane_count != len(self.lanes):
            raise ValueError("lane_count must equal the number of lanes")
        if [lane.index for lane in self.lanes] != list(range(self.lane_count)):
            raise ValueError("lane indexes must be contiguous and UI ordered")
        return self


class SelectFixedLaneRequest(BaseModel):
    """Select one whole fixed lane after guarding the observed layout."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    lane_index: int = Field(ge=0)
    expected_layout_fingerprint: str = Field(min_length=1)

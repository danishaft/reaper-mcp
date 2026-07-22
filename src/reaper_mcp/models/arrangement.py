"""Typed marker and region models."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarkerSnapshot(BaseModel):
    """Read-only marker state using REAPER marker IDs."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0)
    name: str = ""
    start_seconds: float = Field(ge=0.0)
    color: int = Field(default=0, ge=0)


class RegionSnapshot(MarkerSnapshot):
    """Read-only region state using REAPER region IDs."""

    end_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def require_positive_duration(self) -> "RegionSnapshot":
        if self.end_seconds <= self.start_seconds:
            msg = "Region end_seconds must be greater than start_seconds."
            raise ValueError(msg)
        return self


class MarkerList(BaseModel):
    """Read-only marker list."""

    model_config = ConfigDict(extra="forbid")

    markers: list[MarkerSnapshot] = Field(default_factory=list)
    marker_count: int = 0


class RegionList(BaseModel):
    """Read-only region list."""

    model_config = ConfigDict(extra="forbid")

    regions: list[RegionSnapshot] = Field(default_factory=list)
    region_count: int = 0


class CreateMarkerRequest(BaseModel):
    """Input for creating one project marker."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    start_seconds: float = Field(ge=0.0)
    color: int = Field(default=0, ge=0)


class CreateMarkerResult(MarkerList):
    """Result returned after creating one marker."""

    marker: MarkerSnapshot
    changes_applied: bool = True


class MarkerIdentity(BaseModel):
    """Guarded identity for deleting one marker."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0)
    expected_name: str | None = None
    expected_start_seconds: float | None = Field(default=None, ge=0.0)


class DeleteMarkerRequest(BaseModel):
    """Input for deleting one guarded marker."""

    model_config = ConfigDict(extra="forbid")

    marker_identity: MarkerIdentity


class DeleteMarkerResult(MarkerList):
    """Result returned after deleting one marker."""

    deleted_marker_id: int = Field(ge=0)
    changes_applied: bool = True


class CreateRegionRequest(BaseModel):
    """Input for creating one project region."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    color: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_positive_duration(self) -> "CreateRegionRequest":
        if self.end_seconds <= self.start_seconds:
            msg = "Region end_seconds must be greater than start_seconds."
            raise ValueError(msg)
        return self


class CreateRegionResult(RegionList):
    """Result returned after creating one region."""

    region: RegionSnapshot
    changes_applied: bool = True


class RegionIdentity(BaseModel):
    """Guarded identity for deleting one region."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0)
    expected_name: str | None = None
    expected_start_seconds: float | None = Field(default=None, ge=0.0)
    expected_end_seconds: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def require_expected_positive_duration(self) -> "RegionIdentity":
        if (
            self.expected_start_seconds is not None
            and self.expected_end_seconds is not None
            and self.expected_end_seconds <= self.expected_start_seconds
        ):
            msg = "expected_end_seconds must be greater than expected_start_seconds."
            raise ValueError(msg)
        return self


class DeleteRegionRequest(BaseModel):
    """Input for deleting one guarded region."""

    model_config = ConfigDict(extra="forbid")

    region_identity: RegionIdentity


class DeleteRegionResult(RegionList):
    """Result returned after deleting one region."""

    deleted_region_id: int = Field(ge=0)
    changes_applied: bool = True

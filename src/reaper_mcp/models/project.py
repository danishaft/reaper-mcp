"""Typed project and track snapshot models."""

from pydantic import BaseModel, ConfigDict, Field


class ProjectMetadata(BaseModel):
    """Basic active project metadata."""

    model_config = ConfigDict(extra="forbid")

    path: str = ""
    name: str = ""
    dirty: bool = False
    state_change_count: int = 0


class TempoSnapshot(BaseModel):
    """Project tempo and time signature summary."""

    model_config = ConfigDict(extra="forbid")

    bpm: float = 0.0
    beats_per_measure: float = 0.0


class TransportSnapshot(BaseModel):
    """Current REAPER transport state."""

    model_config = ConfigDict(extra="forbid")

    play_state: int = 0


class TrackSnapshot(BaseModel):
    """Read-only track state using REAPER's stable track GUID."""

    model_config = ConfigDict(extra="forbid")

    guid: str
    name: str = ""
    index: int
    color: int = 0
    volume: float = 1.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    armed: bool = False
    selected: bool = False
    media_item_count: int = 0
    folder_depth: int = 0
    recording_input: int = -1
    input_monitoring: bool = False


class MarkerSnapshot(BaseModel):
    """Read-only marker state."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str = ""
    start_seconds: float
    color: int = 0


class RegionSnapshot(MarkerSnapshot):
    """Read-only region state."""

    end_seconds: float


class ProjectSnapshot(BaseModel):
    """Read-only active project snapshot."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectMetadata = Field(default_factory=ProjectMetadata)
    tempo: TempoSnapshot = Field(default_factory=TempoSnapshot)
    transport: TransportSnapshot = Field(default_factory=TransportSnapshot)
    tracks: list[TrackSnapshot] = Field(default_factory=list)
    markers: list[MarkerSnapshot] = Field(default_factory=list)
    regions: list[RegionSnapshot] = Field(default_factory=list)
    selected_track_guids: list[str] = Field(default_factory=list)


class TrackList(BaseModel):
    """Read-only list of tracks."""

    model_config = ConfigDict(extra="forbid")

    tracks: list[TrackSnapshot] = Field(default_factory=list)
    track_count: int = 0


class CreateTrackRequest(BaseModel):
    """Input for creating one REAPER track."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Track", min_length=1, max_length=200)
    index: int | None = Field(default=None, ge=1)
    color: int | None = Field(default=None, ge=0)
    dry_run: bool = False


class CreateTrackResult(BaseModel):
    """Result returned after creating one REAPER track."""

    model_config = ConfigDict(extra="forbid")

    track: TrackSnapshot
    track_count: int
    dry_run: bool = False
    changes_applied: bool = True


class TrackGuidRequest(BaseModel):
    """Input for commands targeting one track by stable GUID."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)


class RenameTrackRequest(TrackGuidRequest):
    """Input for renaming one REAPER track."""

    name: str = Field(min_length=1, max_length=200)


class SetTrackColorRequest(TrackGuidRequest):
    """Input for setting a REAPER track color."""

    color: int = Field(ge=0)


class SetTrackMuteRequest(TrackGuidRequest):
    """Input for setting REAPER track mute state."""

    muted: bool


class SetTrackSoloRequest(TrackGuidRequest):
    """Input for setting REAPER track solo state."""

    soloed: bool


class SetTrackArmRequest(TrackGuidRequest):
    """Input for setting REAPER track record-arm state."""

    armed: bool


class SetTrackVolumeRequest(TrackGuidRequest):
    """Input for setting linear REAPER track gain."""

    volume: float = Field(ge=0.0, le=4.0)


class SetTrackPanRequest(TrackGuidRequest):
    """Input for setting REAPER track pan."""

    pan: float = Field(ge=-1.0, le=1.0)


class SetTrackRecordingRequest(TrackGuidRequest):
    """Input for setting track recording input and monitoring."""

    recording_input: int = Field(ge=-1, le=256)
    input_monitoring: bool = False


class SetTrackFolderDepthRequest(TrackGuidRequest):
    """Input for setting one track's folder depth."""

    folder_depth: int = Field(ge=-1, le=1)


class TrackMutationResult(BaseModel):
    """Result returned after mutating one REAPER track."""

    model_config = ConfigDict(extra="forbid")

    track: TrackSnapshot
    track_count: int
    changes_applied: bool = True


class DeleteTrackResult(BaseModel):
    """Result returned after deleting one REAPER track."""

    model_config = ConfigDict(extra="forbid")

    deleted_track_guid: str
    track_count: int
    changes_applied: bool = True


class MasterTrackSnapshot(BaseModel):
    """Read-only master track state."""

    model_config = ConfigDict(extra="forbid")

    guid: str = ""
    volume: float = 1.0
    pan: float = 0.0
    mute: bool = False


class SetMasterVolumeRequest(BaseModel):
    """Input for setting linear master gain."""

    model_config = ConfigDict(extra="forbid")

    volume: float = Field(ge=0.0, le=4.0)


class SetMasterPanRequest(BaseModel):
    """Input for setting master pan."""

    model_config = ConfigDict(extra="forbid")

    pan: float = Field(ge=-1.0, le=1.0)


class SetMasterMuteRequest(BaseModel):
    """Input for setting master mute state."""

    model_config = ConfigDict(extra="forbid")

    muted: bool


class MasterTrackMutationResult(BaseModel):
    """Result returned after mutating the master track."""

    model_config = ConfigDict(extra="forbid")

    master_track: MasterTrackSnapshot
    changes_applied: bool = True

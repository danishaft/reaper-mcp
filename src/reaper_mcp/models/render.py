"""Typed render models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RenderScope = Literal["project", "selected_region", "regions", "stems"]
RenderFormat = Literal["wav"]
RenderStatus = Literal["started", "running", "completed", "failed"]


class RenderOutputRequest(BaseModel):
    """Input shared by render commands that write files."""

    model_config = ConfigDict(extra="forbid")

    output_path: str = Field(min_length=1)
    overwrite: bool = False
    format: RenderFormat = "wav"


class RenderOutputPlan(BaseModel):
    """Validated render output path details."""

    model_config = ConfigDict(extra="forbid")

    output_path: str = Field(min_length=1)
    output_directory: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    allowed_root: str = Field(min_length=1)
    overwrite: bool = False
    format: RenderFormat = "wav"


class RenderCommandRequest(RenderOutputRequest):
    """Base request for one future render command."""

    scope: RenderScope


class RenderOutputFile(BaseModel):
    """Metadata for one rendered output file."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    size_bytes: int = Field(gt=0)
    exists: bool = True


class RenderTracePoint(BaseModel):
    """One observable point in the bridge render transaction."""

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1)
    elapsed_ms: int = Field(ge=0)
    detail: str = ""


class RenderTransaction(BaseModel):
    """State restoration facts for one completed render transaction."""

    model_config = ConfigDict(extra="forbid")

    settings_restored: bool
    dirty_state_before: bool
    dirty_state_after: bool
    dirty_state_preserved: bool
    output_overwritten: bool = False
    trace: list[RenderTracePoint] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transaction_invariants(self) -> "RenderTransaction":
        """Require restoration and dirty-state facts to agree."""

        if self.dirty_state_before != self.dirty_state_after:
            msg = "A preserved dirty state must have equal before and after values."
            raise ValueError(msg)
        if not self.dirty_state_preserved:
            msg = "A render transaction must preserve the project dirty state."
            raise ValueError(msg)
        return self


class RenderResult(BaseModel):
    """Stable result returned after a completed render."""

    model_config = ConfigDict(extra="forbid")

    scope: RenderScope
    status: Literal["completed"] = "completed"
    primary_output_path: str = Field(min_length=1)
    output_files: list[RenderOutputFile] = Field(min_length=1)
    output_file_count: int = Field(ge=1)
    render_stats: str = ""
    render_stats_summary: str = ""
    transaction: RenderTransaction

    @model_validator(mode="after")
    def validate_output_invariants(self) -> "RenderResult":
        """Keep the primary output and count consistent with the files list."""

        if self.output_file_count != len(self.output_files):
            msg = "output_file_count must match output_files length."
            raise ValueError(msg)
        if self.primary_output_path != self.output_files[0].path:
            msg = "primary_output_path must be the first output file path."
            raise ValueError(msg)
        if not all(output.exists for output in self.output_files):
            msg = "Completed render outputs must all exist."
            raise ValueError(msg)
        if not self.transaction.settings_restored:
            msg = "Completed renders must restore render settings."
            raise ValueError(msg)
        if not self.transaction.dirty_state_preserved:
            msg = "Completed renders must preserve project dirty state."
            raise ValueError(msg)
        required_stages = {
            "render_42230_started",
            "render_42230_returned",
            "transaction_verified",
        }
        actual_stages = {point.stage for point in self.transaction.trace}
        if not required_stages.issubset(actual_stages):
            msg = (
                "Completed renders must include start, return, and verification "
                "trace points."
            )
            raise ValueError(msg)
        return self


class RenderProjectRequest(RenderOutputRequest):
    """Input for rendering the full project."""

    model_config = ConfigDict(extra="forbid")


class RenderProjectResult(RenderResult):
    """Result returned after rendering the full project."""

    scope: Literal["project"] = "project"


class RenderJobStart(BaseModel):
    """Acknowledgement returned before a render job completes."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    scope: Literal["project"] = "project"
    status: Literal["started"] = "started"
    output_path: str = Field(min_length=1)
    overwrite: bool = False


class RenderJobStatus(BaseModel):
    """Status returned while a render job is pending or complete."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    scope: Literal["project"] = "project"
    status: Literal["running", "completed", "failed"]
    output_path: str | None = None
    overwrite: bool = False
    trace: list[RenderTracePoint] = Field(default_factory=list)

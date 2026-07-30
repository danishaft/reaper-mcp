"""MCP mastering-session tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.models.mastering import (
    AlbumContinuityLimits,
    AlbumMetadata,
    AlbumSequenceMode,
    AlbumTrackIntent,
    ApprovedMasteringCandidate,
    CodecPreviewSpecification,
    DeliverySpecification,
    MasteringAlbumProject,
    MasteringCandidate,
    MasteringCandidateComparison,
    MasteringFxOperation,
    MasteringPlan,
    MasteringSession,
    MasteringVersionEntry,
    MasteringWorkflowMode,
    VerifiedMasteringPlanApplication,
)
from reaper_mcp.services.mastering_album_service import MasteringAlbumService
from reaper_mcp.services.mastering_audition_service import MasteringAuditionService
from reaper_mcp.services.mastering_candidate_service import (
    MasteringCandidateService,
)
from reaper_mcp.services.mastering_codec_service import MasteringCodecService
from reaper_mcp.services.mastering_comparison_service import (
    MasteringComparisonService,
)
from reaper_mcp.services.mastering_delivery_service import MasteringDeliveryService
from reaper_mcp.services.mastering_plan_service import MasteringPlanService
from reaper_mcp.services.mastering_project_service import MasteringProjectService
from reaper_mcp.services.mastering_session_service import MasteringSessionService
from reaper_mcp.services.mastering_version_service import MasteringVersionService


def register_mastering_tools(
    server: FastMCP,
    session_service: MasteringSessionService,
    plan_service: MasteringPlanService,
    project_service: MasteringProjectService,
    candidate_service: MasteringCandidateService,
    comparison_service: MasteringComparisonService,
    audition_service: MasteringAuditionService,
    delivery_service: MasteringDeliveryService,
    album_service: MasteringAlbumService,
    codec_service: MasteringCodecService,
    version_service: MasteringVersionService,
) -> None:
    """Register opt-in mastering tools."""

    @server.tool(
        name="create_mastering_session",
        description=(
            "Measure and fingerprint an approved mix, bind engineer intent, and "
            "optionally bind the current REAPER project snapshot. This read-only "
            "handoff does not apply mastering processing."
        ),
    )
    async def create_mastering_session(
        source_path: str,
        workflow_mode: MasteringWorkflowMode,
        desired_outcome: str,
        priorities: list[str] | None = None,
        reference_notes: list[str] | None = None,
        normalization_targets_lufs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return await session_service.create_session(
            source_path,
            workflow_mode,
            desired_outcome,
            priorities=priorities,
            reference_notes=reference_notes,
            normalization_targets_lufs=normalization_targets_lufs,
        )

    @server.tool(
        name="preview_mastering_plan",
        description=(
            "Validate exact master-FX parameter and bypass changes against the "
            "current source, project, master chain, and parameter names. Returns "
            "an approval hash and does not mutate REAPER."
        ),
    )
    async def preview_mastering_plan(
        session: MasteringSession,
        master_track_guid: str,
        operations: list[MasteringFxOperation],
    ) -> dict[str, Any]:
        return await plan_service.preview_plan(
            session.model_dump(mode="json"),
            master_track_guid,
            [operation.model_dump(mode="json") for operation in operations],
        )

    @server.tool(
        name="apply_mastering_plan",
        description=(
            "Revalidate a complete mastering plan and apply its exact master-FX "
            "parameter and bypass changes in one named undo transaction. Requires "
            "the approval hash returned by preview_mastering_plan."
        ),
    )
    async def apply_mastering_plan(
        plan: MasteringPlan,
        approval_hash: str,
    ) -> dict[str, Any]:
        return await plan_service.apply_plan(
            plan.model_dump(mode="json"),
            approval_hash,
        )

    @server.tool(
        name="create_stereo_mastering_project",
        description=(
            "Create a new isolated REAPER project from an approved stereo_mix "
            "session using a short-lived child REAPER process. The interactive "
            "REAPER instance and source file are not changed."
        ),
    )
    async def create_stereo_mastering_project(
        session: MasteringSession,
        project_path: str,
    ) -> dict[str, Any]:
        return await project_service.create_stereo_project(
            session.model_dump(mode="json"),
            project_path,
        )

    @server.tool(
        name="create_mastering_candidate",
        description=(
            "Render the currently applied mastering plan through the isolated "
            "renderer, measure the actual WAV, and return reproducible candidate "
            "evidence. Candidate approval remains pending engineer judgment."
        ),
    )
    async def create_mastering_candidate(
        plan: MasteringPlan,
        application: VerifiedMasteringPlanApplication,
        output_path: str,
        label: str,
        engineer_notes: list[str] | None = None,
    ) -> dict[str, Any]:
        return await candidate_service.create_candidate(
            plan.model_dump(mode="json"),
            application.model_dump(mode="json"),
            output_path,
            label,
            engineer_notes=engineer_notes,
        )

    @server.tool(
        name="compare_mastering_candidates",
        description=(
            "Calculate attenuation-only integrated-LUFS matching for two "
            "candidates from the same source. Reports exact audition gains and "
            "does not claim an artistic preference."
        ),
    )
    async def compare_mastering_candidates(
        candidate_a: MasteringCandidate,
        candidate_b: MasteringCandidate,
    ) -> dict[str, Any]:
        return await comparison_service.compare_candidates(
            candidate_a.model_dump(mode="json"),
            candidate_b.model_dump(mode="json"),
        )

    @server.tool(
        name="prepare_mastering_audition",
        description=(
            "Create gain-matched 32-bit float copies and a new isolated REAPER "
            "project that plays candidate A then B. Verifies both source hashes, "
            "can use blind project labels, and does not touch open REAPER state."
        ),
    )
    async def prepare_mastering_audition(
        candidate_a: MasteringCandidate,
        candidate_b: MasteringCandidate,
        comparison: MasteringCandidateComparison,
        project_path: str,
        blind_labels: bool = True,
        excerpt_start_seconds: float = 0.0,
        excerpt_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await audition_service.prepare(
            candidate_a.model_dump(mode="json"),
            candidate_b.model_dump(mode="json"),
            comparison.model_dump(mode="json"),
            project_path,
            blind_labels=blind_labels,
            excerpt_start_seconds=excerpt_start_seconds,
            excerpt_duration_seconds=excerpt_duration_seconds,
        )

    @server.tool(
        name="approve_mastering_candidate",
        description=(
            "Record explicit engineer listening confirmation and judgment notes "
            "for one candidate in a measured comparison. This approval is "
            "required before delivery."
        ),
    )
    async def approve_mastering_candidate(
        candidate: MasteringCandidate,
        comparison: MasteringCandidateComparison,
        approved_by: str,
        judgment_notes: list[str],
        listening_confirmed: bool,
    ) -> dict[str, Any]:
        return await comparison_service.approve_candidate(
            candidate.model_dump(mode="json"),
            comparison.model_dump(mode="json"),
            approved_by,
            judgment_notes,
            listening_confirmed,
        )

    @server.tool(
        name="deliver_mastering_candidate",
        description=(
            "Generate final WAV variants from an explicitly approved candidate, "
            "apply sample-rate conversion and dither once, measure every final "
            "file, enforce QC, and write JSON plus Markdown manifests."
        ),
    )
    async def deliver_mastering_candidate(
        approval: ApprovedMasteringCandidate,
        specifications: list[DeliverySpecification],
        manifest_path: str,
        summary_path: str,
    ) -> dict[str, Any]:
        return await delivery_service.deliver(
            approval.model_dump(mode="json"),
            [specification.model_dump(mode="json") for specification in specifications],
            manifest_path,
            summary_path,
        )

    @server.tool(
        name="prepare_mastering_album",
        description=(
            "Analyze ordered approved song masters, report adjacent loudness, "
            "true-peak, dynamics, and four-band balance deltas, prepare "
            "gap/fade float assets, and create an isolated REAPER album project "
            "plus PQ/CD-Text preview manifest. DDP remains unavailable."
        ),
    )
    async def prepare_mastering_album(
        metadata: AlbumMetadata,
        sequence_mode: AlbumSequenceMode,
        tracks: list[AlbumTrackIntent],
        project_path: str,
        manifest_path: str,
        continuity_limits: AlbumContinuityLimits | None = None,
        pq_preview_requested: bool = True,
    ) -> dict[str, Any]:
        return await album_service.prepare(
            metadata.model_dump(mode="json"),
            sequence_mode,
            [track.model_dump(mode="json") for track in tracks],
            project_path,
            manifest_path,
            continuity_limits=(
                continuity_limits.model_dump(mode="json")
                if continuity_limits is not None
                else None
            ),
            pq_preview_requested=pq_preview_requested,
        )

    @server.tool(
        name="approve_mastering_album",
        description=(
            "Reverify the album project, manifest, approved song masters, and "
            "sequence assets, then record explicit engineer listening notes. "
            "This does not enable DDP."
        ),
    )
    async def approve_mastering_album(
        album: MasteringAlbumProject,
        approved_by: str,
        judgment_notes: list[str],
        listening_confirmed: bool,
    ) -> dict[str, Any]:
        return await album_service.approve(
            album.model_dump(mode="json"),
            approved_by,
            judgment_notes,
            listening_confirmed,
        )

    @server.tool(
        name="create_mastering_codec_preview",
        description=(
            "Encode an approved master to AAC, MP3, or Opus, decode the actual "
            "bitstream to float WAV, remeasure it, and report loudness, peak, "
            "and four-band deltas. This creates an audition preview, not a "
            "master deliverable."
        ),
    )
    async def create_mastering_codec_preview(
        approval: ApprovedMasteringCandidate,
        specification: CodecPreviewSpecification,
    ) -> dict[str, Any]:
        return await codec_service.create_preview(
            approval.model_dump(mode="json"),
            specification.model_dump(mode="json"),
        )

    @server.tool(
        name="create_mastering_version_set",
        description=(
            "Group independently rendered and approved main, clean, explicit, "
            "instrumental, radio, acapella, or other versions. Revalidates each "
            "source and never derives missing versions from one master."
        ),
    )
    async def create_mastering_version_set(
        release_name: str,
        entries: list[MasteringVersionEntry],
    ) -> dict[str, Any]:
        return await version_service.create_version_set(
            release_name,
            [entry.model_dump(mode="json") for entry in entries],
        )

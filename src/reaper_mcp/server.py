"""MCP server entrypoint for REAPER MCP."""

from reaper_mcp.bridge.file_bridge import FileBridgeClient
from reaper_mcp.config import Settings, get_settings
from reaper_mcp.logging import configure_logging
from reaper_mcp.profiles import ProfiledFastMCP, ToolProfileRegistry
from reaper_mcp.services.arrangement_service import ArrangementService
from reaper_mcp.services.audio_analysis_service import AudioAnalysisService
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService
from reaper_mcp.services.audio_program_analysis_backend import (
    FfmpegProgramAnalysisBackend,
)
from reaper_mcp.services.audio_program_analysis_service import (
    AudioProgramAnalysisService,
)
from reaper_mcp.services.automation_service import AutomationService
from reaper_mcp.services.batch_service import BatchService
from reaper_mcp.services.diagnostics_service import DiagnosticsService
from reaper_mcp.services.fixed_lane_service import FixedLaneService
from reaper_mcp.services.freeze_service import FreezeService
from reaper_mcp.services.fx_service import FxService
from reaper_mcp.services.health_service import HealthService
from reaper_mcp.services.mastering_album_backend import FfmpegAlbumAssetBackend
from reaper_mcp.services.mastering_album_service import MasteringAlbumService
from reaper_mcp.services.mastering_audition_service import (
    FfmpegAuditionBackend,
    MasteringAuditionService,
)
from reaper_mcp.services.mastering_candidate_service import (
    MasteringCandidateService,
)
from reaper_mcp.services.mastering_codec_service import (
    FfmpegCodecPreviewBackend,
    MasteringCodecService,
)
from reaper_mcp.services.mastering_comparison_service import (
    MasteringComparisonService,
)
from reaper_mcp.services.mastering_delivery_service import (
    FfmpegDeliveryBackend,
    MasteringDeliveryService,
)
from reaper_mcp.services.mastering_plan_service import MasteringPlanService
from reaper_mcp.services.mastering_project_service import MasteringProjectService
from reaper_mcp.services.mastering_session_service import MasteringSessionService
from reaper_mcp.services.mastering_version_service import MasteringVersionService
from reaper_mcp.services.media_service import MediaService
from reaper_mcp.services.midi_controller_service import MidiControllerService
from reaper_mcp.services.midi_transform_service import MidiTransformService
from reaper_mcp.services.navigation_service import NavigationService
from reaper_mcp.services.project_controls_service import ProjectControlsService
from reaper_mcp.services.project_service import ProjectService
from reaper_mcp.services.render_service import RenderService
from reaper_mcp.services.routing_service import RoutingService
from reaper_mcp.services.take_service import TakeService
from reaper_mcp.services.template_service import TemplateService
from reaper_mcp.services.tempo_map_service import TempoMapService
from reaper_mcp.services.tempo_service import TempoService
from reaper_mcp.services.transport_service import TransportService
from reaper_mcp.services.vocal_tuning_service import VocalTuningService
from reaper_mcp.services.workflow_service import WorkflowService
from reaper_mcp.tools.arrangement import register_arrangement_tools
from reaper_mcp.tools.audio_analysis import register_audio_analysis_tools
from reaper_mcp.tools.automation import register_automation_tools
from reaper_mcp.tools.batch import register_batch_tools
from reaper_mcp.tools.diagnostics import register_diagnostics_tools
from reaper_mcp.tools.fixed_lane import register_fixed_lane_tools
from reaper_mcp.tools.freeze import register_freeze_tools
from reaper_mcp.tools.fx import register_fx_tools
from reaper_mcp.tools.health import register_health_tool
from reaper_mcp.tools.mastering import register_mastering_tools
from reaper_mcp.tools.media import register_media_tools
from reaper_mcp.tools.midi_controller import register_midi_controller_tools
from reaper_mcp.tools.midi_transform import register_midi_transform_tools
from reaper_mcp.tools.navigation import register_navigation_tools
from reaper_mcp.tools.profiles import register_profile_tools
from reaper_mcp.tools.project import register_project_tools
from reaper_mcp.tools.project_controls import register_project_control_tools
from reaper_mcp.tools.render import register_render_tools
from reaper_mcp.tools.routing import register_routing_tools
from reaper_mcp.tools.take import register_take_tools
from reaper_mcp.tools.templates import register_template_tools
from reaper_mcp.tools.tempo import register_tempo_tools
from reaper_mcp.tools.tempo_map import register_tempo_map_tools
from reaper_mcp.tools.transport import register_transport_tools
from reaper_mcp.tools.vocal_tuning import register_vocal_tuning_tools
from reaper_mcp.tools.workflow import register_workflow_tools


def create_server(settings: Settings | None = None) -> ProfiledFastMCP:
    """Create and configure the MCP server."""

    resolved_settings = settings or get_settings()
    profile_registry = ToolProfileRegistry(resolved_settings.tool_profile)
    server = ProfiledFastMCP("reaper-mcp", profile_registry)
    bridge_client = FileBridgeClient(
        bridge_dir=resolved_settings.bridge_dir,
        timeout_seconds=resolved_settings.bridge_timeout_seconds,
        poll_interval_seconds=resolved_settings.bridge_poll_interval_seconds,
        stale_after_seconds=resolved_settings.bridge_stale_after_seconds,
    )
    register_health_tool(server, HealthService(bridge_client))
    measurement_roots = list(
        dict.fromkeys(
            [
                *resolved_settings.allowed_audio_roots,
                *resolved_settings.allowed_render_roots,
            ]
        )
    )
    measurement_service = AudioMeasurementService(
        FfmpegEbur128Backend(
            resolved_settings.ffmpeg_executable,
            timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
            max_output_bytes=resolved_settings.audio_measurement_max_output_bytes,
        ),
        allowed_audio_roots=measurement_roots,
    )
    program_analysis_service = AudioProgramAnalysisService(
        FfmpegProgramAnalysisBackend(
            resolved_settings.ffmpeg_executable,
            timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
            max_output_bytes=resolved_settings.audio_measurement_max_output_bytes,
        ),
        allowed_audio_roots=measurement_roots,
    )
    project_service = ProjectService(bridge_client)
    fx_service = FxService(bridge_client)
    media_service = MediaService(
        bridge_client,
        allowed_media_source_roots=resolved_settings.allowed_media_source_roots,
    )
    take_service = TakeService(bridge_client)
    fixed_lane_service = FixedLaneService(bridge_client)
    plan_service = MasteringPlanService(bridge_client, fx_service, project_service)
    render_service = RenderService(
        bridge_client,
        render_timeout_seconds=resolved_settings.render_timeout_seconds,
        render_poll_interval_seconds=resolved_settings.render_poll_interval_seconds,
        render_background_confirmed=resolved_settings.render_background_confirmed,
        external_render_enabled=resolved_settings.render_external_enabled,
        reaper_executable=resolved_settings.reaper_executable,
        allowed_render_roots=resolved_settings.allowed_render_roots,
    )
    mastering_project_service = MasteringProjectService(
        allowed_project_roots=resolved_settings.allowed_project_roots,
        reaper_executable=resolved_settings.reaper_executable,
        timeout_seconds=resolved_settings.render_timeout_seconds,
        poll_interval_seconds=resolved_settings.render_poll_interval_seconds,
    )
    register_audio_analysis_tools(
        server,
        AudioAnalysisService(
            allowed_audio_roots=resolved_settings.allowed_audio_roots,
            bridge_client=bridge_client,
        ),
        measurement_service,
        program_analysis_service,
    )
    register_mastering_tools(
        server,
        MasteringSessionService(measurement_service, project_service),
        plan_service,
        mastering_project_service,
        MasteringCandidateService(
            plan_service,
            render_service,
            measurement_service,
        ),
        MasteringComparisonService(),
        MasteringAuditionService(
            FfmpegAuditionBackend(
                resolved_settings.ffmpeg_executable,
                timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
                max_output_bytes=(resolved_settings.audio_measurement_max_output_bytes),
            ),
            mastering_project_service,
            allowed_source_roots=measurement_roots,
        ),
        MasteringDeliveryService(
            FfmpegDeliveryBackend(
                resolved_settings.ffmpeg_executable,
                timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
                max_output_bytes=(resolved_settings.audio_measurement_max_output_bytes),
            ),
            measurement_service,
            program_analysis_service,
            allowed_delivery_roots=resolved_settings.allowed_render_roots,
        ),
        MasteringAlbumService(
            FfmpegAlbumAssetBackend(
                resolved_settings.ffmpeg_executable,
                timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
                max_output_bytes=(resolved_settings.audio_measurement_max_output_bytes),
            ),
            program_analysis_service,
            mastering_project_service,
            allowed_source_roots=measurement_roots,
            allowed_project_roots=resolved_settings.allowed_project_roots,
        ),
        MasteringCodecService(
            FfmpegCodecPreviewBackend(
                resolved_settings.ffmpeg_executable,
                timeout_seconds=resolved_settings.audio_measurement_timeout_seconds,
                max_output_bytes=(resolved_settings.audio_measurement_max_output_bytes),
            ),
            measurement_service,
            program_analysis_service,
            allowed_preview_roots=measurement_roots,
        ),
        MasteringVersionService(allowed_source_roots=measurement_roots),
    )
    register_diagnostics_tools(server, DiagnosticsService(bridge_client))
    register_project_tools(server, project_service)
    register_project_control_tools(server, ProjectControlsService(bridge_client))
    register_media_tools(server, media_service)
    register_midi_transform_tools(server, MidiTransformService(bridge_client))
    register_midi_controller_tools(server, MidiControllerService(bridge_client))
    register_transport_tools(server, TransportService(bridge_client))
    register_template_tools(
        server,
        TemplateService(
            bridge_client,
            allowed_template_roots=resolved_settings.allowed_template_roots,
        ),
    )
    register_fx_tools(server, fx_service)
    register_freeze_tools(server, FreezeService(bridge_client))
    register_arrangement_tools(server, ArrangementService(bridge_client))
    register_batch_tools(server, BatchService(bridge_client))
    register_automation_tools(server, AutomationService(bridge_client))
    register_tempo_tools(server, TempoService(bridge_client))
    register_tempo_map_tools(server, TempoMapService(bridge_client))
    register_take_tools(server, take_service)
    register_fixed_lane_tools(server, fixed_lane_service)
    register_vocal_tuning_tools(
        server,
        VocalTuningService(
            bridge_client,
            project_service,
            media_service,
            take_service,
            fx_service,
        ),
    )
    register_navigation_tools(
        server,
        NavigationService(
            bridge_client,
            allowed_project_roots=resolved_settings.allowed_project_roots,
        ),
    )
    register_routing_tools(server, RoutingService(bridge_client))
    register_workflow_tools(server, WorkflowService(bridge_client))
    register_render_tools(server, render_service)
    register_profile_tools(server, profile_registry)
    return server


def main() -> None:
    """Run the MCP server over the configured transport."""

    settings = get_settings()
    configure_logging(settings.log_level)
    server = create_server(settings)
    if settings.transport == "http":
        from reaper_mcp.rest import run_http_server

        run_http_server(settings, server)
        return
    server.run()


if __name__ == "__main__":
    main()

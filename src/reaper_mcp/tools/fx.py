"""MCP FX tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.models.fx import FxIdentity, TakeFxIdentity
from reaper_mcp.services.fx_service import FxService


def register_fx_tools(server: FastMCP, service: FxService) -> None:
    """Register REAPER FX MCP tools."""

    @server.tool(
        name="list_available_fx",
        description=(
            "Return installed FX entries available to REAPER. "
            "This tool does not change the REAPER project."
        ),
    )
    async def list_available_fx() -> dict[str, Any]:
        return await service.list_available_fx()

    @server.tool(
        name="list_track_fx",
        description=(
            "Return FX on an ordinary track or the master track by stable GUID. "
            "Use get_master_track to read the master GUID."
        ),
    )
    async def list_track_fx(track_guid: str) -> dict[str, Any]:
        return await service.list_track_fx(track_guid=track_guid)

    @server.tool(
        name="list_take_fx",
        description="Return FX on one media take by stable take GUID.",
    )
    async def list_take_fx(take_guid: str) -> dict[str, Any]:
        return await service.list_take_fx(take_guid)

    @server.tool(
        name="add_take_fx",
        description="Add one FX to a media take in one named undo block.",
    )
    async def add_take_fx(
        take_guid: str,
        fx_identifier: str,
        index: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        return await service.add_take_fx(take_guid, fx_identifier, index, enabled)

    @server.tool(
        name="remove_take_fx",
        description=(
            "Remove one take FX after checking its guarded identity. Pass the "
            "fx_identity object returned with the take FX snapshot."
        ),
    )
    async def remove_take_fx(fx_identity: TakeFxIdentity) -> dict[str, Any]:
        return await service.remove_take_fx(fx_identity.model_dump(mode="json"))

    @server.tool(
        name="set_take_fx_enabled",
        description=(
            "Set one take FX enabled state after checking its identity. Pass the "
            "fx_identity object returned with the take FX snapshot."
        ),
    )
    async def set_take_fx_enabled(
        fx_identity: TakeFxIdentity, enabled: bool
    ) -> dict[str, Any]:
        return await service.set_take_fx_enabled(
            fx_identity.model_dump(mode="json"), enabled
        )

    @server.tool(
        name="add_fx",
        description=(
            "Add one FX to an ordinary track or the master track by stable GUID "
            "and FX identifier in one named undo block."
        ),
    )
    async def add_fx(
        track_guid: str,
        fx_identifier: str,
        index: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        return await service.add_fx(
            track_guid=track_guid,
            fx_identifier=fx_identifier,
            index=index,
            enabled=enabled,
        )

    @server.tool(
        name="remove_fx",
        description=(
            "Remove one FX after checking its guarded identity. Pass the fx_identity "
            "object returned with the FX snapshot. "
            "This mutates the project in one named undo block."
        ),
    )
    async def remove_fx(fx_identity: FxIdentity) -> dict[str, Any]:
        return await service.remove_fx(fx_identity=fx_identity.model_dump(mode="json"))

    @server.tool(
        name="set_fx_enabled",
        description=(
            "Set one FX enabled state after checking its guarded identity. Pass the "
            "fx_identity object returned with the FX snapshot. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_fx_enabled(
        fx_identity: FxIdentity,
        enabled: bool,
    ) -> dict[str, Any]:
        return await service.set_fx_enabled(
            fx_identity=fx_identity.model_dump(mode="json"),
            enabled=enabled,
        )

    @server.tool(
        name="get_fx_parameters",
        description=(
            "Return parameters for one FX after checking its guarded identity. Pass "
            "the fx_identity object returned with the FX snapshot. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_fx_parameters(fx_identity: FxIdentity) -> dict[str, Any]:
        return await service.get_fx_parameters(
            fx_identity=fx_identity.model_dump(mode="json")
        )

    @server.tool(
        name="set_fx_parameter",
        description=(
            "Set one FX parameter by guarded FX identity and normalized value "
            "from 0.0 to 1.0. Pass the fx_identity object returned with the FX "
            "snapshot. This mutates the project in one named undo block."
        ),
    )
    async def set_fx_parameter(
        fx_identity: FxIdentity,
        parameter_index: int,
        normalized_value: float,
    ) -> dict[str, Any]:
        return await service.set_fx_parameter(
            fx_identity=fx_identity.model_dump(mode="json"),
            parameter_index=parameter_index,
            normalized_value=normalized_value,
        )

    @server.tool(
        name="get_fx_preset",
        description=(
            "Read one guarded FX preset name using the fx_identity object returned "
            "with the FX snapshot."
        ),
    )
    async def get_fx_preset(fx_identity: FxIdentity) -> dict[str, Any]:
        return await service.get_fx_preset(fx_identity.model_dump(mode="json"))

    @server.tool(
        name="set_fx_preset",
        description=(
            "Set one guarded FX preset in one named undo block using the fx_identity "
            "object returned with the FX snapshot."
        ),
    )
    async def set_fx_preset(
        fx_identity: FxIdentity, preset_name: str
    ) -> dict[str, Any]:
        return await service.set_fx_preset(
            fx_identity.model_dump(mode="json"), preset_name
        )

    @server.tool(
        name="get_fx_preset_index",
        description=(
            "Read the current preset index and count using the fx_identity object "
            "returned with the FX snapshot."
        ),
    )
    async def get_fx_preset_index(
        fx_identity: FxIdentity,
    ) -> dict[str, Any]:
        return await service.get_fx_preset_index(fx_identity.model_dump(mode="json"))

    @server.tool(
        name="set_fx_preset_index",
        description=(
            "Select a factory or user preset by index for one guarded FX in one "
            "named undo block. Pass the fx_identity object returned with the FX "
            "snapshot. Use -2 for factory and -1 for default user preset."
        ),
    )
    async def set_fx_preset_index(
        fx_identity: FxIdentity, preset_index: int
    ) -> dict[str, Any]:
        return await service.set_fx_preset_index(
            fx_identity.model_dump(mode="json"), preset_index
        )

    @server.tool(
        name="navigate_fx_presets",
        description=(
            "Move within one guarded FX preset bank. Positive direction moves "
            "forward; negative direction moves backward. Pass the fx_identity "
            "object returned with the FX snapshot."
        ),
    )
    async def navigate_fx_presets(
        fx_identity: FxIdentity, direction: int
    ) -> dict[str, Any]:
        return await service.navigate_fx_presets(
            fx_identity.model_dump(mode="json"), direction
        )

    @server.tool(
        name="move_fx",
        description=(
            "Move one guarded FX within its track chain in one undo block. Pass the "
            "fx_identity object returned with the FX snapshot."
        ),
    )
    async def move_fx(
        fx_identity: FxIdentity, destination_index: int
    ) -> dict[str, Any]:
        return await service.move_fx(
            fx_identity.model_dump(mode="json"), destination_index
        )

    @server.tool(
        name="copy_fx_chain",
        description="Copy one track's FX chain to another track in one undo block.",
    )
    async def copy_fx_chain(
        source_track_guid: str,
        destination_track_guid: str,
        replace_destination: bool = False,
    ) -> dict[str, Any]:
        return await service.copy_fx_chain(
            source_track_guid, destination_track_guid, replace_destination
        )
